#!/usr/bin/env python3
"""
Deterministisches Telnet- & FTP-Steuerwerkzeug für Anyka BusyBox-Kameras.
- Zustandsbehafteter RFC-854-IAC-Parser (überlebt Paketgrenzen)
- Funktioniert mit 'telnetd -l /bin/sh' (ohne Login) UND '/bin/login' (mit User/Pass)
- Echo-sicheres Exit-Code-Framing (immun gegen PTY-Echo)
- Automatische CRLF->LF-Bereinigung bei Text-/Skript-Uploads per FTP
- get/put geben die MD5-Summe aus -> Vergleich mit 'md5sum' auf der Kamera (Backup-Verifikation!)
"""
import argparse
import ftplib
import hashlib
import io
import os
import re
import socket
import sys
import time

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
TEXT_EXTS = {".sh", ".cgi", ".html", ".htm", ".js", ".css", ".json", ".conf", ".ini", ".m3u", ".txt"}


class AnykaTelnet:
    def __init__(self, host: str, port: int = 23, timeout: float = 15.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.4)
        self._state = "DATA"
        self._iac_cmd = 0
        self.buf = bytearray()

    def _feed(self, chunk: bytes) -> None:
        reply = bytearray()
        for b in chunk:
            if self._state == "DATA":
                if b == IAC:
                    self._state = "IAC"
                else:
                    self.buf.append(b)
            elif self._state == "IAC":
                if b == IAC:
                    self.buf.append(255)
                    self._state = "DATA"
                elif b in (DO, DONT, WILL, WONT):
                    self._iac_cmd = b
                    self._state = "OPT"
                elif b == SB:
                    self._state = "SB"
                else:
                    self._state = "DATA"
            elif self._state == "OPT":
                # Lehne alle Optionen sauber ab -> zwingt telnetd in den einfachen NVT-Modus
                if self._iac_cmd in (DO, DONT):
                    reply.extend((IAC, WONT, b))
                elif self._iac_cmd in (WILL, WONT):
                    reply.extend((IAC, DONT, b))
                self._state = "DATA"
            elif self._state == "SB":
                if b == IAC:
                    self._state = "SB_IAC"
            elif self._state == "SB_IAC":
                self._state = "DATA" if b == SE else "SB"
        if reply:
            self.sock.sendall(bytes(reply))

    def pump(self, duration: float = 0.8) -> str:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                self._feed(chunk)
            except socket.timeout:
                pass
        return self.buf.decode("utf-8", errors="replace")

    def login(self, user: str = "root", password: str = "") -> None:
        text = self.pump(0.9)
        if not text.strip():
            self.sock.sendall(b"\n")
            text = self.pump(0.9)

        low = text.lower()
        if "login:" in low:
            self.sock.sendall((user + "\n").encode("utf-8"))
            text = self.pump(1.0)
            low = text.lower()

        if "password:" in low:
            self.sock.sendall((password + "\n").encode("utf-8"))
            text = self.pump(1.0)

        # Schalte Echo ab und normiere PATH; funktioniert auch wenn telnetd direkt in /bin/sh startet
        self.sock.sendall(b"stty -echo 2>/dev/null; unalias -a 2>/dev/null; export PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH\n")
        self.pump(0.5)
        self.buf.clear()

    def run(self, cmd: str, timeout: float = 30.0) -> tuple[int, str]:
        self.buf.clear()
        # Geteilter String im printf verhindert 100%ig falsche Matches durch lokales PTY-Echo!
        wrapped = f"{cmd}\nprintf '\\n__AGY'\"_RC_%d__\\n\" $?\n"
        self.sock.sendall(wrapped.encode("utf-8"))

        pattern = re.compile(r"\r?\n__AGY_RC_(\d+)__\r?\n")
        first_line = cmd.splitlines()[0].strip() if cmd.strip() else ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump(0.25)
            decoded = self.buf.decode("utf-8", errors="replace")
            m = pattern.search(decoded)
            if m:
                rc = int(m.group(1))
                out = decoded[:m.start()]
                # Falls stty -echo ignoriert wurde: Echo des Befehls und des printf-Wrappers entfernen
                lines = out.splitlines()
                if lines and first_line and first_line in lines[0]:
                    lines = lines[1:]
                lines = [ln for ln in lines if "__AGY'" not in ln]
                return rc, "\n".join(lines).strip()
        raise TimeoutError(f"Telnet-Timeout nach {timeout}s bei Befehl: {cmd!r}\nBisherige Ausgabe:\n{self.buf.decode('utf-8', errors='replace')}")

    def close(self) -> None:
        try:
            self.sock.sendall(b"exit\n")
        except OSError:
            pass
        self.sock.close()


def ftp_connect(host: str, port: int, user: str, password: str) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=15)
    ftp.login(user=user or "anonymous", passwd=password or "")
    ftp.voidcmd("TYPE I")  # Immer Binary-Modus erzwingen
    return ftp


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Anyka Camera Control CLI")
    ap.add_argument("--host", required=True)
    ap.add_argument("--telnet-port", type=int, default=23)
    ap.add_argument("--telnet-user", default="root")
    ap.add_argument("--telnet-pass", default="")
    ap.add_argument("--ftp-port", type=int, default=21)
    ap.add_argument("--ftp-user", default="root", help="Bei Login-Fehler 'anonymous' versuchen (BusyBox ftpd)")
    ap.add_argument("--ftp-pass", default="")

    sub = ap.add_subparsers(dest="mode", required=True)

    p_exec = sub.add_parser("exec")
    p_exec.add_argument("cmd")
    p_exec.add_argument("--timeout", type=float, default=30.0, help="Für dd/Backups auf SD höher setzen (z. B. 300)")

    p_get = sub.add_parser("get")
    p_get.add_argument("remote")
    p_get.add_argument("local")

    p_put = sub.add_parser("put")
    p_put.add_argument("local")
    p_put.add_argument("remote")
    p_put.add_argument("--raw", action="store_true", help="Keine LF-Normalisierung erzwingen")

    args = ap.parse_args()

    if args.mode == "exec":
        tn = AnykaTelnet(args.host, args.telnet_port)
        try:
            tn.login(args.telnet_user, args.telnet_pass)
            rc, out = tn.run(args.cmd, timeout=args.timeout)
            if out:
                print(out)
            return rc
        finally:
            tn.close()

    elif args.mode == "get":
        os.makedirs(os.path.dirname(os.path.abspath(args.local)), exist_ok=True)
        ftp = ftp_connect(args.host, args.ftp_port, args.ftp_user, args.ftp_pass)
        try:
            with open(args.local, "wb") as f:
                ftp.retrbinary(f"RETR {args.remote}", f.write)
            print(f"OK GET {args.remote} -> {args.local} ({os.path.getsize(args.local)} bytes) md5={md5_file(args.local)}")
            return 0
        finally:
            ftp.quit()

    elif args.mode == "put":
        with open(args.local, "rb") as f:
            data = f.read()
        ext = os.path.splitext(args.local)[1].lower()
        if not args.raw and ext in TEXT_EXTS:
            # Verhindert tödliche '\r\n' Shebang-Fehler auf BusyBox!
            data = data.replace(b"\r\n", b"\n")
        ftp = ftp_connect(args.host, args.ftp_port, args.ftp_user, args.ftp_pass)
        try:
            ftp.storbinary(f"STOR {args.remote}", io.BytesIO(data))
            print(f"OK PUT {args.local} -> {args.remote} ({len(data)} bytes) md5={hashlib.md5(data).hexdigest()}")
            return 0
        finally:
            ftp.quit()
    return 1


if __name__ == "__main__":
    sys.exit(main())
