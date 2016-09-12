#!/usr/bin/env python3

import json
import os
import os.path
import sys

import aioxmpp
import aioxmpp.presence
import aioxmpp.roster
from aioxmpp.security_layer import PinType, PublicKeyPinStore
from prompt_toolkit.completion import Completion, Completer
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.shortcuts import prompt_async


async def xmpp_client():
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

  async def get_secret(jid, attempt):
    if attempt > 2:
      return None
    try:
      return await prompt_async("Secret (will not be stored): ", is_password=True)
    except:
      return None

  async def tls_handshake_callback(verifier):
    print("Warning: blindly accepting TLS certificate from %s" % verifier.transport.get_extra_info("server_hostname"))
    return True

  pin_store = PublicKeyPinStore()
  pin_store.import_from_json(config.get("pkps", {}))
  my_jid = aioxmpp.JID.fromstr(config["jid"])
  security = aioxmpp.make_security_layer(get_secret, pin_store=pin_store, pin_type=PinType.PUBLIC_KEY, post_handshake_deferred_failure=tls_handshake_callback)
  client = aioxmpp.PresenceManagedClient(my_jid, security)
  presence = client.summon(aioxmpp.presence.Service)
  roster = client.summon(aioxmpp.roster.Service)

  def name_for_jid(jid):
    try:
      return roster.items[jid].name
    except:
      return str(jid)

  def peer_available(jid, presence):
    print("%s is now online" % name_for_jid(jid.bare()))
  presence.on_available.connect(peer_available)

  def peer_unavailable(jid, presence):
    print("%s is now offline" % name_for_jid(jid.bare()))
  presence.on_unavailable.connect(peer_unavailable)

  def message_received(msg):
    print("%s: %s" % (name_for_jid(msg.from_.bare()),
                      " ".join(msg.body.values())))
  client.stream.register_message_callback("chat", None, message_received)

  class RosterItemCompleter(Completer):
    def get_completions(self, document, complete_event):
      if document.find_backwards(" ") != None:
        return
      if document.find_backwards(":") != None:
        return
      for item in roster.items.values():
        if item.name.startswith(document.text):
          yield Completion(item.name + ": ", start_position=-len(document.text), display=item.name)
  completer = RosterItemCompleter()

  try:
    async with client.connected() as stream:
      next_recipient = None
      while True:
        line = await prompt_async("%s> " % (next_recipient or ""), patch_stdout=True, completer=completer)
        if line.startswith("/"):
          try:
            command, *args = line[1:].split(" ")
            if command == "roster":
              rows = []
              status_map = {"away": "a", "xa": "x"}
              for jid in filter(lambda jid: jid != my_jid, roster.items):
                item = roster.items[jid]
                rows.append((item.name,
                             str(jid),
                             item.subscription))
              widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
              for row in rows:
                print("   ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
            elif command == "name":
              try:
                jid = args[0]
                name = args[1]
              except IndexError:
                print("usage: /name JID NAME")
              else:
                roster.items[jid].name = name
            elif command == "quit":
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
              print("/roster          print the roster")
              print("/name JID NAME   set the name for a contact")
              print("/quit            disconnect and then quit (also ctrl-d, ctrl-c)")
              print("/help            this help")
            else:
              print("unrecognised command")
          except Exception as e:
            print("exception handling command: %s" % e)
        else:
          try:
            try:
              recipient, message = line.split(": ", 1)
            except ValueError:
              if next_recipient is not None:
                recipient = next_recipient
                message = line
              else:
                print("recipient: message")
                continue
            jid_for_name = lambda recipient: next((jid for jid, item in roster.items.items() if item.name == recipient), None)
            jid = jid_for_name(recipient)
            if jid is None:
              if next_recipient is not None and recipient != next_recipient:
                recipient = next_recipient
                jid = jid_for_name(recipient)
                if jid is None:
                  print("unknown recipient: %s" % recipient)
                  continue
              else:
                print("unknown recipient: %s" % recipient)
                continue
            msg = aioxmpp.Message(to=jid, type_="chat")
            msg.body[None] = message
            await stream.send_and_wait_for_sent(msg)
            next_recipient = recipient
          except Exception as e:
            print("exception sending message: %s" % e)
  except Exception as e:
    print("Failed to connect: %s" % e)

if __name__ == "__main__":
  import asyncio
  import logging

  logging.basicConfig(level=logging.CRITICAL)
  loop = asyncio.get_event_loop()
  try:
    loop.run_until_complete(xmpp_client())
  except (KeyboardInterrupt, EOFError):
    pass
  except Exception as e:
    print("Exception in main loop: %s" % e)
  finally:
    loop.close()
