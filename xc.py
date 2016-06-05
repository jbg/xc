#!/usr/bin/env python3

import getpass
import json
import os
import os.path
import readline
import string
import sys
import threading

from sleekxmpp import ClientXMPP


class Client(ClientXMPP):
  def __init__(self, jid, secret, connected, callback):
    super(Client, self).__init__(jid, secret)
    self.connected = connected
    self.callback = callback
    self.add_event_handler("session_start", self.session_start)
    self.add_event_handler("changed_status", self.changed_status)
    self.add_event_handler("message", self.message)

  def session_start(self, e):
    self.send_presence()
    self.get_roster()
    self.connected.acquire()
    self.connected.notify()
    self.connected.release()
    del self.connected

  def changed_status(self, presence):
    if not str(presence["from"]).startswith(self.jid + "/"):
      self.callback("status", presence)

  def message(self, msg):
    self.callback("message", msg)

  
class Console:
  def __init__(self):
    super(Console, self).__init__()
    readline.parse_and_bind("tab: complete")
    readline.set_completer(self.completer)
    readline.set_completer_delims(": ")

  def prepend(self, line):
    print("\x1b[2K\r%s\n> " % line, end="")
    readline.redisplay()

  def completer(self, text, state):
    if text.startswith("/"):
      commands = ("/roster", "/quit")
      completions = [c for c in commands if c.startswith(text)]
    else:
      roster = self.xmpp.client_roster
      names = [roster[k]["name"] for k in roster.keys() if k != self.xmpp.jid]
      completions = [n+": " for n in names if n.startswith(text)]
    try:
      return completions[state]
    except IndexError:
      return None

  def on_event(self, event, *args):
    if event == "message":
      msg = args[0]
      # TODO don't print the whole stanza!
      self.prepend(str(msg))
    elif event == "status":
      presence = args[0]
      self.prepend("%s: %s" % (presence["from"], presence["show"]))

  def loop(self):
    next_recipient = None
    while True:
      try:
        line = input("%s> " % (next_recipient or "")).strip()
      except (EOFError, KeyboardInterrupt):
        self.xmpp.disconnect()
        sys.exit(0)
        break
      else:
        if line.startswith("/"):
          command, *args = line[1:].split(" ")
          if command == "roster":
            roster = self.xmpp.client_roster
            if "raw" in args:
              print("\n".join("%s:\n%s\n%s" % (jid, roster[jid], roster[jid].resources) for jid in roster if jid != self.xmpp.jid))
            else:
              rows = []
              status_map = {"away": "a", "xa": "x"}
              for jid in filter(lambda jid: jid != self.xmpp.jid, roster):
                entry = roster[jid]
                rows.append(("".join(status_map.get(r["show"], "*") for r in entry.resources.values()),
                             entry["name"],
                             jid,
                             entry["subscription"]))
            widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
            if "all" not in args:
              rows = filter(lambda row: row[0], rows)
            for row in rows:
              print("   ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
          elif command == "quit":
            self.xmpp.disconnect()
            sys.exit(0)
            break
          else:
            print("unrecognised command")
        else:
          try:
            recipient, message = line.split(": ", 1)
          except ValueError:
            if next_recipient is not None:
              recipient = next_recipient
            else:
              print("recipient: message")
              continue
          roster = self.xmpp.client_roster
          try:
            jid = next(roster[k].jid for k in roster.keys() if roster[k]["name"] == recipient)
          except StopIteration:
            print("unknown recipient")
          else:
            self.xmpp.send_message(mto=jid, mbody=message)
            next_recipient = recipient


if __name__ == "__main__":
  try:
    with open(os.path.join(os.getenv("HOME"), ".xc.conf"), "r") as config_file:
      config = json.load(config_file)
    if "jid" not in config:
      raise Exception("No JID")
  except Exception as e:
    print("Error reading configuration file.")
    print(str(e))
    print("Please create ~/.xc.conf with content like:")
    print("{\"jid\": \"foo@bar.com\"}")
    sys.exit(1)

  connected = threading.Condition()

  console = Console()
  secret = getpass.getpass("Secret (will not be stored): ")
  console.xmpp = Client(config["jid"], secret, connected, console.on_event)
  secret = None

  console.xmpp.connect()
  console.xmpp.process(block=False)

  connected.acquire()
  connected.wait()
  connected.release()
  connected = None

  console.loop()
