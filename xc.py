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
  def __init__(self, jid, secret, connected):
    super(Client, self).__init__(jid, secret)
    self.connected = connected
    self.add_event_handler("session_start", self.session_start)
    self.add_event_handler("message", self.message)

  def session_start(self, e):
    self.send_presence()
    self.get_roster()
    self.connected.acquire()
    self.connected.notify()
    self.connected.release()
    del self.connected

  def message(self, msg):
    self.prepend(message)

  def prepend(self, line):
    print("\x1b[2K\r%s\n> " % line, end="")
    readline.redisplay()
  
class Console:
  prompt = "> "

  def __init__(self, xmpp):
    super(Console, self).__init__()
    self.xmpp = xmpp
    readline.parse_and_bind("tab: complete")
    readline.set_completer(self.completer)
    readline.set_completer_delims(": ")

  def completer(self, text, state):
    if text.startswith("/"):
      commands = ("/roster", "/quit")
      completions = [c for c in commands if c.startswith(text)]
    else:
      roster = self.xmpp.client_roster
      names = [roster[k]['name'] for k in roster.keys() if k != self.xmpp.jid]
      completions = [n+": " for n in names if n.startswith(text)]
    try:
      return completions[state]
    except IndexError:
      return None

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
            if args and args[0] == "raw":
              for jid in roster:
                if jid != self.xmpp.jid:
                  print("%s:\n%s\n%s" % (jid, roster[jid], roster[jid].resources))
            else:
              rows = []
              status_map = {"away": "a", "xa": "x"}
              for jid in roster:
                if jid == self.xmpp.jid:
                  continue
                entry = roster[jid]
                statuses = "".join(status_map.get(r["show"], "*") for r in entry.resources.values())
                rows.append({'statuses': statuses,
                             'name': entry['name'],
                             'jid': jid,
                             'subscription': entry['subscription']})
              statuses_col_width = max(len(row['statuses']) for row in rows)
              name_col_width = max(len(row['name']) for row in rows) + 2
              jid_col_width = max(len(row['jid']) for row in rows) + 2
              for row in rows:
                if not row["statuses"] and "all" not in args:
                  continue
                print(row['statuses'].ljust(statuses_col_width) + "  " + row['name'].ljust(name_col_width) + row['jid'].ljust(jid_col_width) + row['subscription'])
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
            jid = next(roster[k].jid for k in roster.keys() if roster[k]['name'] == recipient)
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

  secret = getpass.getpass("Secret (will not be stored): ")
  xmpp = Client(config['jid'], secret, connected)
  secret = None

  xmpp.connect()
  xmpp.process(block=False)

  connected.acquire()
  connected.wait()
  connected.release()
  connected = None

  print("Connected")
  Console(xmpp).loop()
