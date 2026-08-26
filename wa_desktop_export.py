#!/usr/bin/env python3
"""
wa_desktop_export.py — Replicate WhatsApp's "Export chat" (desktop format), including
media, straight from the local macOS WhatsApp Desktop database (ChatStorage.sqlite).

Everything the macOS app stores at rest is plaintext SQLite (no key needed), so this
reads the message store read-only and reconstructs the exact `_chat.txt` + media zip
that WhatsApp's own desktop export produces — the same format the project's
whatsapp_converter.py already ingests.

Stdlib only. Optional: `phonenumbers` for pretty international phone-number grouping.

Usage:
    python3 wa_desktop_export.py list [--db PATH] [--all]
    python3 wa_desktop_export.py export --jid <jid> [--out DIR] [--me NAME]
    python3 wa_desktop_export.py export --pk <session_z_pk> [--out DIR]

Read-only: the database is opened immutable; the app's live store is never modified.
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone

# ---- constants -------------------------------------------------------------

# Core Data (Mac absolute time) epoch = 2001-01-01 UTC.
COREDATA_EPOCH = 978307200

# Unicode formatting characters WhatsApp uses in exports.
LRM = "‎"   # LEFT-TO-RIGHT MARK  (prefixes system / attachment content)
LRE = "‪"   # LEFT-TO-RIGHT EMBEDDING (wraps phone numbers)
PDF = "‬"   # POP DIRECTIONAL FORMATTING
NNBSP = " "  # NARROW NO-BREAK SPACE (after '~' for push-name senders)
NBSP = " "  # NO-BREAK SPACE (between phone-number groups)

# ZMESSAGETYPE -> (export token, default extension)
MEDIA_TYPES = {
    1: ("PHOTO", "jpg"),
    2: ("VIDEO", "mp4"),
    3: ("AUDIO", "opus"),
    8: ("DOCUMENT", "bin"),
    11: ("VIDEO", "mp4"),   # auto-play / gif-style clips are stored as mp4
    15: ("STICKER", "webp"),
    23: ("VIDEO", "mp4"),   # short "video note"
}

# Standard client-rendered system strings (stored with empty ZTEXT).
E2E_NOTICE = ("Messages and calls are end-to-end encrypted. "
              "Only people in this chat can read, listen to, or share them.")

DEFAULT_DB = os.path.expanduser(
    "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite")

try:
    import phonenumbers  # optional
except Exception:  # pragma: no cover
    phonenumbers = None


# ---- helpers ---------------------------------------------------------------

def open_db(path):
    """Open the ChatStorage db read-only + immutable (non-destructive)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"ChatStorage.sqlite not found at: {path}")
    uri = "file:%s?immutable=1" % path.replace("?", "%3f")
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def media_root_for(db_path):
    """The folder ZMEDIALOCALPATH is relative to: <container>/Message/ ."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "Message")


def coredata_to_dt(ts, tz):
    """Core Data timestamp -> aware datetime in the requested tz (or local).

    Returns None for missing or out-of-range values (some rows carry sentinels).
    """
    if ts is None:
        return None
    try:
        dt = datetime.fromtimestamp(ts + COREDATA_EPOCH, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return dt.astimezone(tz) if tz else dt.astimezone()


def digits_of_jid(jid):
    """Real phone digits from a JID — ONLY for phone JIDs (@s.whatsapp.net / @c.us).

    A @lid local part is a numeric LinkedID, NOT a phone number, so it returns "".
    """
    if not jid or not (jid.endswith("@s.whatsapp.net") or jid.endswith("@c.us")):
        return ""
    local = jid.split("@", 1)[0]
    local = re.split(r"[-:]", local, 1)[0]
    return local if local.isdigit() else ""


def _clean_name(s):
    """Drop empty / junk display names (e.g. the '+EAA=' LID placeholder)."""
    s = (s or "").strip()
    return "" if (not s or "=" in s) else s


def format_phone(jid):
    """Render a phone JID the way WhatsApp does: LRE +cc<nbsp>groups PDF.

    For opaque IDs (e.g. @lid) with no real phone, return the bare local id
    rather than fabricating a '+number'.
    """
    digits = digits_of_jid(jid)
    if not digits:
        return jid.split("@", 1)[0] if jid else ""
    if phonenumbers:
        try:
            num = phonenumbers.parse("+" + digits, None)
            intl = phonenumbers.format_number(
                num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            return LRE + intl.replace(" ", NBSP) + PDF
        except Exception:
            pass
    return LRE + "+" + digits + PDF


# ---- name resolution -------------------------------------------------------

def contacts_db_for(db_path):
    """ContactsV2.sqlite lives beside ChatStorage.sqlite in the group container."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "ContactsV2.sqlite")


class Resolver:
    """Resolves a JID to the display string WhatsApp would show as the sender.

    Push names come from ChatStorage (ZWAPROFILEPUSHNAME); saved contact names
    come from the separate ContactsV2.sqlite (ZWAADDRESSBOOKCONTACT).
    """

    def __init__(self, con, db_path):
        self.contacts = {}   # jid -> saved full name
        self.push = {}       # jid -> push name
        self.phone = {}      # jid -> saved phone number
        self.username = {}   # jid -> @username
        cur = con.cursor()
        for r in cur.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME"):
            if r["ZJID"] and r["ZPUSHNAME"]:
                self.push[r["ZJID"]] = r["ZPUSHNAME"]
        cpath = contacts_db_for(db_path)
        if os.path.exists(cpath):
            try:
                ccon = open_db(cpath)
                for r in ccon.execute(
                        "SELECT ZWHATSAPPID, ZLID, ZFULLNAME, ZGIVENNAME, ZLASTNAME, "
                        "ZPHONENUMBER, ZUSERNAME FROM ZWAADDRESSBOOKCONTACT"):
                    name = (r["ZFULLNAME"] or
                            " ".join(x for x in (r["ZGIVENNAME"], r["ZLASTNAME"]) if x) or
                            "").strip()
                    for key in (r["ZWHATSAPPID"], r["ZLID"]):
                        if not key:
                            continue
                        if name:
                            self.contacts[key] = name
                        if r["ZPHONENUMBER"]:
                            self.phone[key] = r["ZPHONENUMBER"]
                        if r["ZUSERNAME"]:
                            self.username[key] = r["ZUSERNAME"]
                ccon.close()
            except sqlite3.Error:
                pass

    def phone_display(self, jid):
        """Best-effort human phone for a JID (may be hidden behind a @lid)."""
        if not jid:
            return ""
        if digits_of_jid(jid):                       # real phone JID
            return format_phone(jid).strip(LRE + PDF)
        if jid in self.phone:                        # @lid resolved via contacts
            return self.phone[jid]
        return "(hidden)"

    def sender(self, jid, contact_hint=None):
        """Return the formatted sender string for a message author JID."""
        if jid and jid in self.contacts:
            return self.contacts[jid]                 # saved contact: plain name
        if contact_hint:
            return contact_hint                       # group member saved name
        if jid and jid in self.push:
            return "~" + NNBSP + self.push[jid]       # non-contact: ~ push name
        return format_phone(jid)                      # last resort: phone number


# ---- chat listing ----------------------------------------------------------

def list_chats(con, include_dms=True):
    """Return chat sessions (groups always; 1:1 when include_dms).

    Each entry: pk, jid, name, is_group, messages, last (datetime), members.
    """
    cur = con.cursor()
    members = {row["ZCHATSESSION"]: row["c"] for row in cur.execute(
        "SELECT ZCHATSESSION, COUNT(*) c FROM ZWAGROUPMEMBER GROUP BY ZCHATSESSION")}
    out = []
    for r in cur.execute(
            "SELECT s.Z_PK, s.ZCONTACTJID, s.ZPARTNERNAME, s.ZGROUPINFO, "
            "       s.ZLASTMESSAGEDATE, "
            "  (SELECT COUNT(*) FROM ZWAMESSAGE m WHERE m.ZCHATSESSION=s.Z_PK) mc "
            "FROM ZWACHATSESSION s"):
        jid = r["ZCONTACTJID"] or ""
        is_group = bool(r["ZGROUPINFO"]) or jid.endswith("@g.us")
        is_newsletter = jid.endswith("@newsletter")
        if not is_group and not include_dms:
            continue
        if is_newsletter:
            continue
        out.append({
            "pk": r["Z_PK"],
            "jid": jid,
            "name": r["ZPARTNERNAME"] or jid or f"chat-{r['Z_PK']}",
            "is_group": is_group,
            "messages": r["mc"] or 0,
            "last": coredata_to_dt(r["ZLASTMESSAGEDATE"], None),
            "members": members.get(r["Z_PK"], 0),
        })
    out.sort(key=lambda c: (c["last"] or datetime.min.replace(tzinfo=timezone.utc)),
             reverse=True)
    return out


def _session_by_jid(con, jid):
    r = con.execute("SELECT Z_PK FROM ZWACHATSESSION WHERE ZCONTACTJID=?",
                    (jid,)).fetchone()
    return r["Z_PK"] if r else None


# ---- the export core -------------------------------------------------------

def _iter_messages(con, pk):
    """Messages of a session in chronological (export) order."""
    return con.execute(
        "SELECT Z_PK, ZSORT, ZISFROMME, ZMESSAGETYPE, ZMESSAGEDATE, ZFROMJID, "
        "       ZGROUPMEMBER, ZMEDIAITEM, ZTEXT "
        "FROM ZWAMESSAGE WHERE ZCHATSESSION=? "
        "ORDER BY ZSORT ASC, ZMESSAGEDATE ASC, Z_PK ASC", (pk,)).fetchall()


def _member_map(con, pk):
    """ZWAGROUPMEMBER.Z_PK -> (member jid, saved contact name)."""
    m = {}
    for r in con.execute(
            "SELECT Z_PK, ZMEMBERJID, ZCONTACTNAME FROM ZWAGROUPMEMBER "
            "WHERE ZCHATSESSION=?", (pk,)):
        m[r["Z_PK"]] = (r["ZMEMBERJID"], r["ZCONTACTNAME"] or None)
    return m


def _media_row(con, media_pk):
    if not media_pk:
        return None
    return con.execute(
        "SELECT ZMEDIALOCALPATH, ZFILESIZE, ZTITLE FROM ZWAMEDIAITEM WHERE Z_PK=?",
        (media_pk,)).fetchone()


def build_export(con, pk, db_path, me_name="You", tz=None):
    """Reconstruct one chat. Returns (chat_name, chat_text, media_list, stats).

    media_list: list of (export_filename, absolute_source_path_or_None).
    """
    sess = con.execute(
        "SELECT ZCONTACTJID, ZPARTNERNAME, ZGROUPINFO FROM ZWACHATSESSION "
        "WHERE Z_PK=?", (pk,)).fetchone()
    if not sess:
        raise ValueError(f"No chat session with Z_PK={pk}")
    jid = sess["ZCONTACTJID"] or ""
    chat_name = sess["ZPARTNERNAME"] or jid or f"chat-{pk}"
    is_group = bool(sess["ZGROUPINFO"]) or jid.endswith("@g.us")

    resolver = Resolver(con, db_path)
    members = _member_map(con, pk)
    mroot = media_root_for(db_path)

    blocks = []          # each is a full message string (no trailing CRLF)
    media = []           # (export_name, src_path_or_None)
    stats = {"messages": 0, "media": 0, "media_present": 0, "media_missing": 0}

    idx = 0
    for row in _iter_messages(con, pk):
        idx += 1
        stats["messages"] += 1
        dt = coredata_to_dt(row["ZMESSAGEDATE"], tz)
        stamp = dt.strftime("%d/%m/%Y, %H:%M:%S") if dt else "??/??/????, ??:??:??"

        # ---- who sent it ----
        if row["ZISFROMME"]:
            sender = me_name
        elif is_group and row["ZGROUPMEMBER"] in members:
            mjid, hint = members[row["ZGROUPMEMBER"]]
            sender = resolver.sender(mjid, hint)
        elif is_group:
            sender = resolver.sender(row["ZFROMJID"])
        else:
            # 1:1: incoming is the partner; prefer the saved session name
            sender = chat_name if chat_name else resolver.sender(jid)

        mtype = row["ZMESSAGETYPE"]
        text = row["ZTEXT"] or ""
        line_lrm = ""        # leading LRM on the whole line (attachments)
        content = None

        # ---- media ----
        if mtype in MEDIA_TYPES:
            mrow = _media_row(con, row["ZMEDIAITEM"])
            token, defext = MEDIA_TYPES[mtype]
            ext = defext
            src = None
            if mrow and mrow["ZMEDIALOCALPATH"]:
                rel = mrow["ZMEDIALOCALPATH"]
                e = os.path.splitext(rel)[1].lstrip(".").lower()
                if e:
                    ext = e
                cand = os.path.join(mroot, rel)
                if os.path.exists(cand):
                    src = cand
            fname = "%08d-%s-%s.%s" % (
                idx, token, dt.strftime("%Y-%m-%d-%H-%M-%S") if dt else "0", ext)
            media.append((fname, src))
            stats["media"] += 1
            stats["media_present" if src else "media_missing"] += 1
            line_lrm = LRM
            content = LRM + "<attached: %s>" % fname
            if text:                       # caption
                content += "\n" + text
        elif text:
            content = text
        elif mtype == 10:                  # E2E notice (empty text)
            content = LRM + E2E_NOTICE
            sender = chat_name
        else:
            # unknown empty/system message type — skip rather than emit a blank
            idx -= 1
            stats["messages"] -= 1
            continue

        blocks.append("%s[%s] %s: %s" % (line_lrm, stamp, sender, content))

    # WhatsApp: CRLF terminates every message; internal newlines stay LF.
    chat_text = "".join(b + "\r\n" for b in blocks)
    return chat_name, chat_text, media, stats


def build_members_text(con, pk, db_path, resolver=None, tz=None, exported_at=None):
    """Return a _members.txt (TSV + header) for a group, or None for a 1:1 chat."""
    sess = con.execute(
        "SELECT ZCONTACTJID, ZPARTNERNAME, ZGROUPINFO FROM ZWACHATSESSION WHERE Z_PK=?",
        (pk,)).fetchone()
    if not sess:
        return None
    jid = sess["ZCONTACTJID"] or ""
    if not (bool(sess["ZGROUPINFO"]) or jid.endswith("@g.us")):
        return None
    resolver = resolver or Resolver(con, db_path)

    gi = con.execute(
        "SELECT ZCREATIONDATE, ZCREATORJID, ZSUBJECTOWNERJID FROM ZWAGROUPINFO "
        "WHERE ZCHATSESSION=?", (pk,)).fetchone()
    rows = con.execute(
        "SELECT ZMEMBERJID, ZCONTACTNAME, ZFIRSTNAME, ZISADMIN, ZISACTIVE "
        "FROM ZWAGROUPMEMBER WHERE ZCHATSESSION=?", (pk,)).fetchall()

    members = []
    for r in rows:
        mjid = r["ZMEMBERJID"] or ""
        name = (_clean_name(resolver.contacts.get(mjid))
                or _clean_name(r["ZCONTACTNAME"])
                or _clean_name(r["ZFIRSTNAME"]))
        members.append({
            "jid": mjid,
            "name": name,
            "push": resolver.push.get(mjid, ""),
            "phone": resolver.phone_display(mjid),
            "username": resolver.username.get(mjid, ""),
            "admin": bool(r["ZISADMIN"]),
            "active": r["ZISACTIVE"] is None or bool(r["ZISACTIVE"]),
        })
    members.sort(key=lambda m: (not m["admin"],
                                (m["name"] or m["push"] or m["jid"]).lower()))

    n_admin = sum(1 for m in members if m["admin"])
    n_active = sum(1 for m in members if m["active"])
    creator = gi["ZCREATORJID"] if gi else ""
    created = coredata_to_dt(gi["ZCREATIONDATE"], tz) if gi else None
    exported_at = exported_at or datetime.now()

    out = []
    out.append(f"# Group members — {sess['ZPARTNERNAME'] or jid}")
    out.append(f"# Group JID     : {jid}")
    if created:
        out.append(f"# Created       : {created.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if creator:
        cname = resolver.contacts.get(creator) or resolver.push.get(creator) or ""
        out.append(f"# Created by    : {creator}" + (f"  ({cname})" if cname else ""))
    out.append(f"# Members       : {len(members)} total, {n_active} active, "
               f"{n_admin} admin")
    out.append(f"# Exported      : {exported_at.strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("#")
    out.append("# Tab-separated. 'phone (hidden)' means the member uses phone-number "
               "privacy (@lid) and is not in your address book.")
    out.append("\t".join(["#", "name", "phone", "username", "role",
                          "status", "pushname", "member_jid"]))
    for i, m in enumerate(members, 1):
        out.append("\t".join([
            str(i),
            m["name"] or "",
            m["phone"] or "",
            ("@" + m["username"]) if m["username"] else "",
            "admin" if m["admin"] else "member",
            "active" if m["active"] else "left",
            m["push"] or "",
            m["jid"] or "",
        ]))
    return "\n".join(out) + "\n"


def safe_name(name):
    """Filesystem-safe chat name for the zip filename."""
    n = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", name).strip().strip(".")
    return (n or "chat")[:120]


def write_zip(con, pk, db_path, out_dir, me_name="You", tz=None,
              info_title=True, timestamp=True):
    """Export a chat to `<out_dir>/WhatsApp Chat - <name> - <ts>.zip`.

    Adds a `_members.txt` for group chats. Returns (path, stats).
    """
    exported_at = datetime.now()
    chat_name, chat_text, media, stats = build_export(
        con, pk, db_path, me_name=me_name, tz=tz)
    resolver = Resolver(con, db_path)  # reused for the members file
    members_txt = build_members_text(
        con, pk, db_path, resolver=resolver, tz=tz, exported_at=exported_at)

    os.makedirs(out_dir, exist_ok=True)
    suffix = (" - " + exported_at.strftime("%Y%m%d_%H%M%S")) if timestamp else ""
    zip_path = os.path.join(
        out_dir, "WhatsApp Chat - %s%s.zip" % (safe_name(chat_name), suffix))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_chat.txt", chat_text.encode("utf-8"))
        if members_txt:
            z.writestr("_members.txt", members_txt.encode("utf-8"))
        if info_title:
            z.writestr("info.txt", ("Title: %s\n" % chat_name).encode("utf-8"))
        for fname, src in media:
            if src:
                z.write(src, fname)
    stats["zip"] = zip_path
    stats["name"] = chat_name
    stats["members_file"] = bool(members_txt)
    return zip_path, stats


# ---- CLI -------------------------------------------------------------------

def _tzinfo(name):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def cmd_list(args):
    con = open_db(args.db)
    chats = list_chats(con, include_dms=args.all)
    print("%-4s %-6s %-8s %-16s  %s" % ("#", "msgs", "members", "last", "name"))
    for i, c in enumerate(chats):
        last = c["last"].strftime("%Y-%m-%d %H:%M") if c["last"] else ""
        kind = "group" if c["is_group"] else "dm"
        print("%-4d %-6d %-8s %-16s  %s" % (
            i, c["messages"], (c["members"] if c["is_group"] else kind), last,
            c["name"]))
    print("\n%d chats (%s)" % (len(chats), "all" if args.all else "groups only"))


def cmd_export(args):
    con = open_db(args.db)
    tz = _tzinfo(args.tz)
    pk = args.pk
    if pk is None:
        if not args.jid:
            sys.exit("Provide --jid or --pk")
        pk = _session_by_jid(con, args.jid)
        if pk is None:
            sys.exit("No chat with jid %s" % args.jid)
    zip_path, stats = write_zip(con, pk, args.db, args.out, me_name=args.me, tz=tz)
    print("Exported: %s" % zip_path)
    print("  messages=%d  media=%d (present=%d, not-downloaded=%d)" % (
        stats["messages"], stats["media"], stats["media_present"],
        stats["media_missing"]))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB, help="Path to ChatStorage.sqlite")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="List chats")
    pl.add_argument("--all", action="store_true", help="Include 1:1 chats (not just groups)")
    pl.set_defaults(func=cmd_list)

    pe = sub.add_parser("export", help="Export a chat to a WhatsApp-style zip")
    g = pe.add_mutually_exclusive_group()
    g.add_argument("--jid", help="Chat JID (…@g.us / …@s.whatsapp.net / …@lid)")
    g.add_argument("--pk", type=int, help="ZWACHATSESSION.Z_PK")
    pe.add_argument("--out", default="wa_exports", help="Output directory")
    pe.add_argument("--me", default="You", help="Display name for your own messages")
    pe.add_argument("--tz", default=None, help="IANA tz for timestamps (default: system local)")
    pe.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
