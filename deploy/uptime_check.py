"""Tiny uptime check with no extra software. Run every few minutes from ANOTHER machine (or a free service such as
UptimeRobot / Better Stack pointed at /v1/health, which does the same).

    python deploy/uptime_check.py https://resumewise.example.com
Exit code 0 = healthy, 1 = down. Combine with cron + `mail`, or any scheduler that alerts on a non-zero exit.
"""
import json
import sys
import urllib.request


def main(base):
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/v1/health", timeout=10) as r:
            ok = r.status == 200 and json.loads(r.read().decode()).get("status") == "ok"
    except Exception as exc:  # noqa: BLE001
        print("DOWN:", exc)
        return 1
    print("OK" if ok else "DOWN: unhealthy answer")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python uptime_check.py https://your-domain")
    sys.exit(main(sys.argv[1]))
