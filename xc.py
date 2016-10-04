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
from prompt_toolkit.interface import CommandLineInterface
from prompt_toolkit.shortcuts import prompt_async, create_asyncio_eventloop, create_prompt_application
from prompt_toolkit.token import Token
from prompt_toolkit.validation import Validator, ValidationError


async def xmpp_client():
  try:
    with open(os.path.join(os.getenv("HOME"), ".xc.conf"), "r") as config_file:
      config = json.load(config_file)
    if "jid" not in config:
      raise Exception("No JID")
  except Exception as e:
    print("Error reading configuration file.\n" + str(e) + "Please create ~/.xc.conf with content like:\n{\"jid\": \"foo@bar.com\"}")
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

  class RosterItemAndCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
      text = document.text
      if not text or " " in text or ":" in text:
        return
      if text[0] == "/":
        part = text[1:]
        for command in ("roster", "name", "add", "del", "help", "quit"):
          if command.startswith(part):
            yield Completion(command + " ", start_position=-len(part), display=command)
      elif roster is not None:
        for item in roster.items.values():
          if item.name.startswith(text):
            yield Completion(item.name + ": ", start_position=-len(text), display=item.name)

  completer = RosterItemAndCommandCompleter()
  history = InMemoryHistory()

  next_recipient = None
  def get_prompt_tokens(_):
    return ((Token.Prompt, "%s> " % (next_recipient or "")),)

  cli_app = create_prompt_application(get_prompt_tokens=get_prompt_tokens,
                                      completer=completer,
                                      reserve_space_for_menu=0,
                                      history=history,
                                      get_title=lambda: "xc")
  cli_loop = create_asyncio_eventloop()
  cli = CommandLineInterface(application=cli_app, eventloop=cli_loop)
  above_prompt = cli.stdout_proxy()

  def name_for_jid(jid):
    try:
      return roster.items[jid].name
    except:
      return str(jid)

  def peer_available(jid, presence):
    above_prompt.write("%s is now online\n" % name_for_jid(jid.bare()))
  presence.on_available.connect(peer_available)

  def peer_unavailable(jid, presence):
    above_prompt.write("%s is now offline\n" % name_for_jid(jid.bare()))
  presence.on_unavailable.connect(peer_unavailable)

  def message_received(msg):
    above_prompt.write("%s: %s\n" % (name_for_jid(msg.from_.bare()), " ".join(msg.body.values())))
  client.stream.register_message_callback("chat", None, message_received)

  try:
    async with client.connected() as stream:
      while True:
        try:
          document = await cli.run_async()
        except (KeyboardInterrupt, EOFError):
          break
        line = document.text
        if line.startswith("/"):
          try:
            command, *args = line[1:].split(" ")
            if command == "roster":
              rows = [(item.name, str(jid), item.subscription) for jid, item in roster.items.items() if jid != my_jid]
              widths = [max(len(row[i] or "") for row in rows) for i in range(len(rows[0] or ""))]
              for row in rows:
                above_prompt.write("   ".join((cell or "").ljust(widths[i]) for i, cell in enumerate(row)) + "\n")
            elif command == "name":
              try:
                jid = args[0]
                name = args[1]
              except IndexError:
                above_prompt.write("usage: /name JID NAME\n")
              else:
                roster.items[jid].name = name
            elif command == "add":
              try:
                jid = args[0]
              except IndexError:
                above_prompt.write("usage: /add JID\n")
              else:
                jid = aioxmpp.JID.fromstr(jid)
                await roster.set_entry(jid)
                roster.subscribe(jid)
                roster.approve(jid)
            elif command == "del":
              try:
                jid = args[0]
              except IndexError:
                above_prompt.write("usage: /del JID\n")
              else:
                jid = aioxmpp.JID.fromstr(jid)
                await roster.remove_entry(jid)
            elif command == "quit":
              break
            elif command == "help":
              above_prompt.write("NAME: MESSAGE    send MESSAGE to NAME\n"
                                 "MESSAGE          send MESSAGE to the last correspondent\n"
                                 "/roster          print the roster\n"
                                 "/add JID         add JID to the roster\n"
                                 "/del JID         remove JID from the roster\n"
                                 "/name JID NAME   set the name of JID to NAME\n"
                                 "/quit            disconnect and then quit (also ctrl-d, ctrl-c)\n"
                                 "/help            this help\n")
            else:
              above_prompt.write("unrecognised command\n")
          except Exception as e:
            above_prompt.write("exception handling command: %s\n" % e)
        else:
          try:
            try:
              recipient, message = line.split(": ", 1)
            except ValueError:
              if next_recipient is not None:
                recipient = next_recipient
                message = line
              else:
                above_prompt.write("recipient: message\n")
                continue
            jid_for_name = lambda r: next((jid for jid, item in roster.items.items() if item.name == r), None)
            jid = jid_for_name(recipient)
            if jid is None:
              if next_recipient is not None and recipient != next_recipient:
                recipient = next_recipient
                jid = jid_for_name(recipient)
            if jid is None:
              above_prompt.write("unknown recipient: %s\n" % recipient)
              continue
            msg = aioxmpp.Message(to=jid, type_="chat")
            msg.body[None] = message
            await stream.send_and_wait_for_sent(msg)
            next_recipient = recipient
          except Exception as e:
            above_prompt.write("exception sending message: %s\n" % e)

    print("Disconnecting…")
    client.stop()
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
