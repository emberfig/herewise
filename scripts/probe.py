#!/usr/bin/env python3
"""Phase 1: prove the K40 answers. No application logic here.

Usage: python scripts/probe.py [ip] [port]
"""
import sys
from zk import ZK


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.201"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 4370

    zk = ZK(ip, port=port, timeout=10, password=0,
            force_udp=False, ommit_ping=False)

    conn = None
    try:
        print(f"connecting to {ip}:{port} ...")
        conn = zk.connect()
        conn.disable_device()

        print("\n--- device ---")
        print("name      ", conn.get_device_name())
        print("serial    ", conn.get_serialnumber())
        print("firmware  ", conn.get_firmware_version())
        print("platform  ", conn.get_platform())
        print("time      ", conn.get_time())

        print("\n--- capacity ---")
        conn.read_sizes()
        print(f"users        {conn.users} / {conn.users_cap}")
        print(f"fingers      {conn.fingers} / {conn.fingers_cap}")
        print(f"records      {conn.records} / {conn.rec_cap}")

        users = conn.get_users()
        print(f"\n--- users ({len(users)}) ---")
        for u in users[:10]:
            print(f"  uid={u.uid} id={u.user_id} name={u.name!r} priv={u.privilege}")
        if len(users) > 10:
            print(f"  ... and {len(users) - 10} more")

        records = conn.get_attendance()
        print(f"\n--- attendance ({len(records)}) ---")
        for r in records[:20]:
            print(f"  {r.user_id:>8}  {r.timestamp}  status={r.status} punch={r.punch}")
        if len(records) > 20:
            print(f"  ... and {len(records) - 20} more")

    except Exception as e:
        print(f"\nFAILED: {type(e).__name__}: {e}")
        print("\ncheck, in order:")
        print("  1. cable connected, device powered on")
        print("  2. ping 192.168.1.201  -> should reply")
        print("  3. PC adapter is static 192.168.1.100 / 255.255.255.0, gateway blank")
        print("  4. device Menu > Comm > Ethernet shows 192.168.1.201")
        print("  5. try force_udp=True")
        sys.exit(1)
    finally:
        if conn:
            try:
                conn.enable_device()   # never leave the device frozen
            finally:
                conn.disconnect()      # still runs if enabling fails
            print("\ndisconnected cleanly")


if __name__ == "__main__":
    main()
