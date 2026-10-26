#!/usr/bin/env python3
import ftplib
import hashlib
import os
import sys

BACKUP_DIR = sys.argv[1]
HOST = sys.argv[2]
USER = "root"
PASS = ""

os.makedirs(f"{BACKUP_DIR}/mtd", exist_ok=True)
os.makedirs(f"{BACKUP_DIR}/jffs2", exist_ok=True)
os.makedirs(f"{BACKUP_DIR}/etc", exist_ok=True)
os.makedirs(f"{BACKUP_DIR}/usr_sbin", exist_ok=True)
os.makedirs(f"{BACKUP_DIR}/sd_scripts", exist_ok=True)

def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def get_file(ftp, remote, local):
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        ftp.retrbinary(f"RETR {remote}", f.write)
    sz = os.path.getsize(local)
    csum = md5_file(local)
    print(f"GET {remote} -> {local} ({sz} bytes) md5={csum}")
    return csum

def main():
    ftp = ftplib.FTP()
    ftp.connect(HOST, 21, timeout=15)
    ftp.login(user=USER, passwd=PASS)
    ftp.voidcmd("TYPE I")
    
    # 1. Download MTD backup files
    print("=== Downloading MTD Partition Images ===")
    mtd_files = ["MANIFEST.txt", "MD5SUMS"] + [f"mtdblock{i}.bin" for i in range(7)]
    for mf in mtd_files:
        get_file(ftp, f"/mnt/backup_mtd/{mf}", f"{BACKUP_DIR}/mtd/{mf}")
    
    # 2. Download /etc/jffs2 files
    print("\n=== Downloading /etc/jffs2 Files ===")
    jffs2_names = ftp.nlst("/etc/jffs2")
    for jf in jffs2_names:
        basename = os.path.basename(jf)
        if basename in (".", ".."):
            continue
        try:
            get_file(ftp, f"/etc/jffs2/{basename}", f"{BACKUP_DIR}/jffs2/{basename}")
        except Exception as e:
            print(f"Skip /etc/jffs2/{basename}: {e}")

    # 3. Download /etc init scripts
    print("\n=== Downloading /etc init scripts ===")
    etc_files = [
        "/etc/init.d/rcS",
        "/etc/init.d/rc.local",
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/passwd",
        "/etc/shadow"
    ]
    for ef in etc_files:
        try:
            get_file(ftp, ef, f"{BACKUP_DIR}/etc/{os.path.basename(ef)}")
        except Exception as e:
            print(f"Skip {ef}: {e}")

    # 4. Download /usr/sbin scripts
    print("\n=== Downloading /usr/sbin scripts ===")
    try:
        sbin_names = ftp.nlst("/usr/sbin")
        for sf in sbin_names:
            basename = os.path.basename(sf)
            if sf.endswith(".sh") or sf.endswith(".script") or sf.endswith(".conf"):
                try:
                    get_file(ftp, sf, f"{BACKUP_DIR}/usr_sbin/{basename}")
                except Exception as e:
                    print(f"Skip {sf}: {e}")
    except Exception as e:
        print(f"nlst /usr/sbin error: {e}")

    # 5. Download SD scripts
    print("\n=== Downloading SD setup scripts ===")
    sd_files = [
        "/mnt/_config.sh",
        "/mnt/anyka_ipc.sh",
        "/mnt/anyka_cfg_color.ini",
        "/mnt/anyka_cfg_night.ini",
        "/mnt/custom/web_interface/www/cgi-bin/ptz.cgi",
        "/mnt/custom/web_interface/www/cgi-bin/webui.old",
        "/mnt/custom/web_interface/www/cgi-bin/list.cgi",
        "/mnt/custom/web_interface/www/cgi-bin/record.cgi",
        "/mnt/custom/web_interface/www/index.html"
    ]
    for sdf in sd_files:
        try:
            get_file(ftp, sdf, f"{BACKUP_DIR}/sd_scripts/{os.path.basename(sdf)}")
        except Exception as e:
            print(f"Skip {sdf}: {e}")

    ftp.quit()
    print("\n=== Backup download complete! ===")

if __name__ == "__main__":
    main()
