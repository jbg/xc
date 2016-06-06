#!/usr/bin/env python3

import getpass
import json
import logging
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
    self.next_recipient = None

  def prepend(self, line):
    print("\x1b[2K\r%s\n%s> %s" % (line, self.next_recipient or "", readline.get_line_buffer()), end="")

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
      from_jid = msg["from"].bare
      try:
        roster = self.xmpp.client_roster
        name = roster[from_jid]["name"]
      except:
        name = from_jid
      self.prepend("%s: %s" % (name, msg["body"]))
    elif event == "status":
      presence = args[0]
      self.prepend("%s is now %s" % (presence["from"], presence["show"] or "online"))

  def loop(self):
    while True:
      try:
        line = input("%s> " % (self.next_recipient or "")).strip()
      except (EOFError, KeyboardInterrupt):
        self.xmpp.disconnect()
        sys.exit(0)
        break
      else:
        if not line:
          continue
        elif line.startswith("/"):
          command, *args = line[1:].split(" ")
          if command == "roster":
            roster = self.xmpp.client_roster
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
          elif command == "name":
            try:
              jid = args[0]
              name = args[1]
            except IndexError:
              print("usage: /name JID NAME")
            else:
              self.xmpp.update_roster(jid, name=name)
          elif command == "quit":
            self.xmpp.disconnect()
            sys.exit(0)
            break
          elif command == "help":
            print("To send a message, type a contact's name (tab-completion is available),")
            print("followed by a colon and space, followed by your message. After the first")
            print("message, xc defaults to sending to the same contact.")
            print("")
            print("Example:")
            print("")
            print("   michael: hello")
            print("")
            print("Commands:")
            print("")
            print("/roster          print non-offline contacts")
            print("/roster all      print all contacts")
            print("/name JID NAME   set the name for a contact")
            print("/quit            disconnect and then quit (also ctrl-d, ctrl-c)")
            print("/help            this help")
          else:
            print("unrecognised command")
        else:
          try:
            recipient, message = line.split(": ", 1)
          except ValueError:
            if self.next_recipient is not None:
              recipient = self.next_recipient
              message = line
            else:
              print("recipient: message")
              continue
          roster = self.xmpp.client_roster
          def jid_for_name(name):
            try:
              return next(roster[k].jid for k in roster.keys() if roster[k]["name"] == name)
            except StopIteration:
              return None
          jid = jid_for_name(recipient)
          if jid is None:
            if self.next_recipient is not None and recipient != self.next_recipient:
              recipient = self.next_recipient
              jid = jid_for_name(recipient)
              if jid is None:
                print("unknown recipient")
                continue
          self.xmpp.send_message(mto=jid, mbody=message)
          self.next_recipient = recipient


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

  logging.basicConfig(level=logging.ERROR)

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
