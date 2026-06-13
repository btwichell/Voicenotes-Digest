"""Send iMessage via AppleScript."""

import os
import subprocess

from dotenv import load_dotenv

load_dotenv()


def send_sms(message: str, phone_number: str | None = None) -> None:
    phone_number = phone_number or os.environ["DIGEST_PHONE_NUMBER"]
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{phone_number}" of targetService
        send "{message}" to targetBuddy
    end tell
    '''
    subprocess.run(["osascript", "-e", script], check=True)
    print("iMessage sent.")


if __name__ == "__main__":
    send_sms("bootcamp test message")
