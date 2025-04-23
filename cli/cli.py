# cli.py
import os
import readline

import pyfiglet
from .commands import commands, get_mininet_macs, TEST_MODE, handle_help


def setup_autocomplete():
    readline.parse_and_bind("tab: complete")
    readline.set_completer(lambda text, state: [cmd for cmd in commands if cmd.startswith(text)][state])


def run_cli():
    setup_autocomplete()
    
    title = pyfiglet.figlet_format("NGN Tester")
    print(title)

    print("Welcome to the Flow Manager for Mininet (WebSocket)!")
    print(f"Running in test mode: {TEST_MODE.upper()}")
    handle_help(None)

    global hosts_mac
    hosts_mac = get_mininet_macs()
    if not hosts_mac:
        print("No MAC addresses found. Make sure Mininet is running.")
        return

    while True:
        try:
            command = input("\ntester> ").strip().lower()
            if command in commands:
                commands[command]["handler"](hosts_mac)
            else:
                print("Unknown command. Type 'help' for list.")
        except KeyboardInterrupt:
            print("\nUse 'exit' to quit.")


if __name__ == "__main__":
    run_cli()
