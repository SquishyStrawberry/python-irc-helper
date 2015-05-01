#!/usr/bin/env python3
# Since Imports are based on sys.path, we need to add the parent directory.
import os
import random
import re
import requests
import sqlite3
import sys
import time

from bs4 import BeautifulSoup

# From Django
url_validator = re.compile(
    r"^(?:(?:http|ftp)s?://)"  # http:// or https://
    r"((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$", re.IGNORECASE)

parent_directory = os.sep.join(os.path.abspath(__file__).split(os.sep)[:-2])
if parent_directory not in sys.path:
    sys.path.insert(0, parent_directory)

from irc_helper import IRCBot, IRCError

FLAGS = {
    "admin": "a",
    "whitelist": "w",
    "ignore": "i",
}
ATTACKS = [
    "shoots a plasma bolt at",
    "hurls a pebble at",
    "tackles",
    "tail-whips",
    "charges",
    "unsheathes his teeth and bites"
]
GREETS = [
    "welcomingly nuzzles and licks",
    "welcomingly nuzzles",
    "welcomingly licks",
    "welcomingly tail-slaps",
    "playfully nuzzles and licks",
    "playfully nuzzles",
    "playfully licks",
    "playfully tail-slaps",
    "tosses a pebble at",
    "joyfully waggles his tail at",
    "cheerfully waggles his tail at",
    "playfully waggles his tail at",
    "welcomes"
]


class IRCHelper(IRCBot):
    def __init__(self, database_name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_commands = []
        self.private_commands = []
        self.command_database = sqlite3.connect(database_name)
        self.irc_cursor = self.command_database.cursor()
        self.irc_cursor.execute("SELECT name FROM sqlite_master WHERE type=\"table\"")
        tables = tuple(map(lambda x: x[0], self.irc_cursor.fetchall()))
        if "Commands" not in tables:
            self.irc_cursor.execute("CREATE TABLE Commands (id INTEGER PRIMARY KEY, trigger TEXT, response TEXT)")
        if "Flags" not in tables:
            self.irc_cursor.execute("CREATE TABLE Flags (id INTEGER PRIMARY KEY, username TEXT, flags TEXT)")

    # To add a command.
    # For commands that are functions.
    def advanced_command(self, private_message=False):
        return self.channel_commands.append if not private_message else self.private_commands.append

    # Use this if your function returns (trigger, command)
    def basic_command(self, *args, **kwargs):
        def basic_decorator(command):
            trigger, response = command(*args, **kwargs)
            self.irc_cursor.execute("SELECT * FROM Commands")
            if self.irc_cursor.fetchone() is None:
                self.irc_cursor.execute("INSERT INTO Commands VALUES (0,?,?)", (trigger, response))
            else:
                self.irc_cursor.execute("SELECT trigger FROM Commands WHERE trigger=? AND response=?",
                                        (trigger, response))
                if self.irc_cursor.fetchone() is None:
                    self.irc_cursor.execute("INSERT INTO Commands(trigger,response) VALUES (?,?)",
                                            (trigger, response))
            return command

        return basic_decorator

    def forget_basic_command(self, trigger):
        self.irc_cursor.execute("DELETE FROM Commands WHERE trigger=?", (trigger,))

    def handle_block(self, block):
        block_data = super().handle_block(block)
        if block_data.get("sender") != self.nick:
            if block_data.get("command", "").upper() == "PRIVMSG" and block_data.get("message", ""):
                if block_data.get("recipient") == self.channel:
                    command_list = self.channel_commands
                elif block_data.get("recipient") == self.nick:
                    command_list = self.private_commands
                else:
                    command_list = []
                for func_command in command_list:
                    if func_command(self, block_data.get("message"), block_data.get("sender")) is not None:
                        break
                self.irc_cursor.execute("SELECT trigger,response FROM Commands")
                for trigger, response in self.irc_cursor.fetchall():
                    matched = re.match(trigger, block_data.get("message", ""))
                    if matched:
                        self.send_message(response.replace("${nick}", block_data.get("sender")))
                        break
            elif block_data.get("command", "").upper() == "JOIN":
                if FLAGS["ignore"] not in self.get_flags(block_data.get("sender", "")):
                    greet = random.choice(GREETS)
                    if "{nick}" in greet:
                        greet = greet.format(nick=block_data.get("sender"))
                    else:
                        greet += block_data.get("sender", "")
                    self.send_action(greet)

    def add_flag(self, username, flag):
        if flag in FLAGS:
            flag = FLAGS.get(flag)
        elif flag not in FLAGS.values():
            raise IRCError("Unknown flag! Valid flags are {}".format(", ".join(FLAGS.values())))
        self.irc_cursor.execute("SELECT * FROM Flags WHERE username=?", (username,))
        if self.irc_cursor.fetchone() is None:
            self.irc_cursor.execute("INSERT INTO Flags VALUES (0,?,?)", (username, flag))
        else:
            old_flags = self.get_flags(username)
            new_flags = "".join(sorted(old_flags + flag))
            self.irc_cursor.execute("UPDATE Flags WHERE username=? SET flags=?", (username, new_flags))

    def get_flags(self, username):
        self.irc_cursor.execute("SELECT flags FROM Flags WHERE username=?", (username,))
        raw_flags = self.irc_cursor.fetchone()
        if raw_flags:
            raw_flags = raw_flags[0]
        else:
            raw_flags = ""
        return tuple(raw_flags)

    def quit(self):
        self.started = False
        self.command_database.commit()
        self.command_database.close()
        self.leave_channel()
        self.socket.close()

    def start_up(self):
        super().start_up()
        self.send_action("enters the arena!")

    def apply_commands(self):
        """
        A base set of commands.
        Arguments:
            bot: A IRCHelper instance.
        Effect:
            Adds a bunch of sample commands to bot.
        """

        @self.advanced_command(False)
        def url_title(bot, message, sender):
            url_match = url_validator.search(message.strip())
            if not url_match:
                return
            req = requests.get(message.strip(), headers={"User-Agent": "Py3 TitleFinder"})
            if req.ok:
                soup = BeautifulSoup(req.text)
                bot.send_message("{}: The URL title is \"{}\"".format(sender, soup.title.text))
                # TODO Implement proper Youtube API
            else:
                bot.send_message("{}: Wasn't able to get URL info! [{}]".format(sender, req.status_code))
            return True

        @self.advanced_command(False)
        def learn_trigger(bot, message, sender):
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! learn").lower()
            if command == respond_to and len(message.split("->", 1)) >= 2 and FLAGS["whitelist"] in bot.get_flags(sender):
                bot.irc_cursor.execute("SELECT * FROM Commands WHERE trigger=? AND response=?", message.split(" ", 2)[2].split(" -> ", 1))
                if bot.irc_cursor.fetchone() is None:
                    bot.send_action("has been trained by {}!".format(sender))
                    @self.basic_command()
                    def learn_comm():
                        return message.split(" ", 2)[2].split(" -> ", 1)
                else:
                    bot.send_action("already knows that!")
            elif FLAGS["whitelist"] not in bot.get_flags(sender):
                bot.send_action("doesn't want to be trained by {}!".format(sender))
            return command == respond_to or None

        @self.advanced_command(False)
        def forget_trigger(bot, message, sender):
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! forget").lower()
            if command == respond_to and len(message.split(" ")) >= 3:
                trigger = message.split(" ", 2)[2]
                bot.irc_cursor.execute("SELECT response FROM Commands WHERE trigger=?", (trigger,))
                response = (bot.irc_cursor.fetchone() or [None])[0]
                print(trigger, response)
                if response is not None:
                    bot.send_action("forgot {} -> {}".format(trigger, response))
                    bot.forget_basic_command(trigger)
                else:
                    bot.send_action("doesn't know that!")
            return command == respond_to or None

        @self.advanced_command(False)
        def attack(bot, message, sender):
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! attack").lower()
            if command == respond_to and len(message.split(" ")) >= 3:
                bot.send_action("{} {}!".format(random.choice(ATTACKS), message.split(" ")[1]))
            return command == respond_to or None

        @self.advanced_command(False)
        def eat(bot, message, sender):
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! eat").lower()
            if command == respond_to and len(message.split(" ")) >= 3:
                victim = message.split(" ", 2)[2]
                bot.send_action("eats {}!".format(victim))
                if "stomach" not in bot.__dict__:
                    bot.stomach = []
                bot.stomach.append(victim)
            return command == respond_to or None

        @self.advanced_command(False)
        def spit(bot, message, sender):
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! spit").lower()
            if command == respond_to and len(message.split(" ")) >= 3:
                victim = message.split(" ", 2)[2]
                if "stomach" not in bot.__dict__:
                    bot.stomach = []
                try:
                    victim_id = bot.stomach.index(victim)
                except ValueError:
                    return
                else:
                    if victim_id != -1:
                        del bot.stomach[victim_id]
                        bot.send_action("spits out {}!".format(victim))
                    else:
                        bot.send_action("hasn't eaten {} yet!".format(victim))
            return command == respond_to or None

        @self.advanced_command(False)
        def show_stomach(bot, message, sender):
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! stomach").lower()
            if "stomach" not in bot.__dict__:
                bot.stomach = []
            if command == respond_to:
                stomachs = ", ".join(bot.stomach)
                if stomachs:
                    bot.send_action("is digesting {}!".format(stomachs))
                else:
                    bot.send_action("hasn't eaten anything yet!")
            return command == respond_to or None

        @self.advanced_command(False)
        def vomit(bot, message, sender):
            if "stomach" not in bot.__dict__:
                bot.stomach = []
            command = " ".join(message.split(" ")[:2]).lower()
            respond_to = (bot.nick.lower() + "! vomit").lower()
            if command == respond_to:
                if bot.stomach:
                    bot.send_action("empties his stomach!")
                    bot.stomach = []
                else:
                    bot.send_action("hasn't eaten anything yet!")
            return command == respond_to or None

        @self.advanced_command(True)
        def clear_commands(bot, message, sender):
            if message.lower().strip() == "purge_commands" and FLAGS["admin"] in bot.get_flags(sender):
                bot.cursor.execute("DELETE FROM Commands")

        @self.advanced_command(True)
        def whitelist(bot, message, sender):
            nicknames = message.lower().strip().split(" ")
            if nicknames[0] == "append_whitelist":
                for i in nicknames[1:]:
                    bot.add_flag(i, FLAGS["whitelist"])

        @self.advanced_command(True)
        def terminate(bot, message, sender):
            if message == "terminate" and FLAGS["admin"] in bot.get_flags(sender):
                bot.quit()

        @self.advanced_command(True)
        def list_commands(bot, message, sender):
            if message == "list_commands":
                bot.irc_cursor.execute("SELECT trigger,response FROM Commands")
                for trigger, response in bot.irc_cursor.fetchall():
                    bot.send_message("{} -> {}".format(trigger, response), sender)
                    time.sleep(.01)
