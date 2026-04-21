"""
gui.py - Tkinter GUI for the chat client
Handles all socket communication directly to avoid threading conflicts.
"""

import threading
import socket
import json
import queue
import time
import tkinter as tk
from tkinter import scrolledtext, simpledialog, messagebox
from chat_utils import *
from chat_bot_client import ChatBotClient
from textblob import TextBlob


def get_sentiment(text):
    polarity = TextBlob(text).sentiment.polarity
    if polarity > 0.1:
        return "😊 Positive"
    elif polarity < -0.1:
        return "😡 Negative"
    else:
        return "😐 Neutral"


# States
S_LOGGEDIN = 1
S_CHATTING = 2


class ChatGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat App")
        self.root.geometry("520x620")
        self.root.configure(bg="#f0f0f0")

        self.s = None
        self.me = ""
        self.peer = ""
        self.state = S_LOGGEDIN
        self.running = False
        self.msg_queue = queue.Queue()
        self.sock_lock = threading.Lock()  # single mutex for all socket access
        self.bot = ChatBotClient(name="Bot", model="phi4-mini")

        self._build_ui()
        self._login()

    def _build_ui(self):
        self.status_var = tk.StringVar(value="Not connected")
        tk.Label(self.root, textvariable=self.status_var,
                 bg="#4a90d9", fg="white", font=("Arial", 10, "bold"),
                 anchor="w", padx=10, pady=4).pack(fill=tk.X)

        self.chat_display = scrolledtext.ScrolledText(
            self.root, state="disabled", wrap=tk.WORD,
            bg="white", fg="#222", font=("Arial", 11),
            relief=tk.FLAT, padx=8, pady=8)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

        self.chat_display.tag_config("me",     foreground="#1a73e8", font=("Arial", 11, "bold"))
        self.chat_display.tag_config("peer",   foreground="#e53935", font=("Arial", 11, "bold"))
        self.chat_display.tag_config("system", foreground="#555",    font=("Arial", 10, "italic"))
        self.chat_display.tag_config("bot",    foreground="#6a0dad", font=("Arial", 11, "bold"))

        bottom = tk.Frame(self.root, bg="#f0f0f0")
        bottom.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.msg_input = tk.Entry(bottom, font=("Arial", 12), relief=tk.SOLID, bd=1)
        self.msg_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self.msg_input.bind("<Return>", lambda e: self._send_message())
        tk.Button(bottom, text="Send", font=("Arial", 11, "bold"),
                  bg="#4a90d9", fg="white", relief=tk.FLAT,
                  padx=14, pady=6, cursor="hand2",
                  command=self._send_message).pack(side=tk.LEFT, padx=(6, 0))

        btn_frame = tk.Frame(self.root, bg="#f0f0f0")
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        for label, cmd in [("Who's Online", self._who),
                            ("Connect",      self._connect_peer),
                            ("Time",         self._time),
                            ("Disconnect",   self._disconnect_peer)]:
            tk.Button(btn_frame, text=label, font=("Arial", 9),
                      bg="#e0e0e0", relief=tk.FLAT, padx=8, pady=4,
                      cursor="hand2", command=cmd).pack(side=tk.LEFT, padx=3)

        bot_frame = tk.Frame(self.root, bg="#f0f0f0")
        bot_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Label(bot_frame, text="🤖 Chatbot:", font=("Arial", 9, "bold"),
                 bg="#f0f0f0").pack(side=tk.LEFT, padx=(0, 4))
        self.bot_input = tk.Entry(bot_frame, font=("Arial", 11), relief=tk.SOLID, bd=1)
        self.bot_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.bot_input.bind("<Return>", lambda e: self._ask_bot())
        tk.Button(bot_frame, text="Ask", font=("Arial", 10, "bold"),
                  bg="#6a0dad", fg="white", relief=tk.FLAT,
                  padx=10, pady=4, cursor="hand2",
                  command=self._ask_bot).pack(side=tk.LEFT, padx=(6, 0))

    def _login(self):
        name = simpledialog.askstring("Login", "Enter your username:", parent=self.root)
        if not name:
            self.root.destroy()
            return
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.connect(SERVER)
            mysend(self.s, json.dumps({"action": "login", "name": name}))
            resp = json.loads(myrecv(self.s))
            if resp["status"] == "ok":
                self.me = name
                self._append("system", f"Welcome, {name}! Use the buttons below.\n")
                self._update_status()
                self.running = True
                threading.Thread(target=self._recv_loop, daemon=True).start()
                self.root.after(100, self._process_queue)
            elif resp["status"] == "duplicate":
                messagebox.showerror("Login Failed", "Username already taken!")
                self.root.destroy()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.root.destroy()

    def _recv_loop(self):
        import select
        while self.running:
            try:
                read, _, _ = select.select([self.s], [], [], 0.2)
                if self.s in read:
                    acquired = self.sock_lock.acquire(timeout=0.1)
                    if acquired:
                        try:
                            raw = myrecv(self.s)
                            if raw:
                                self.msg_queue.put(raw)
                        finally:
                            self.sock_lock.release()
            except:
                break

    def _send_cmd(self, action_json):
        """Send a command and get the response, holding the mutex the whole time."""
        with self.sock_lock:
            try:
                mysend(self.s, action_json)
                resp = myrecv(self.s)
                return json.loads(resp)
            except Exception:
                return {"results": "", "status": "error"}

    def _process_queue(self):
        while not self.msg_queue.empty():
            raw = self.msg_queue.get()
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "exchange":
                    text = msg.get("message", "")
                    sender = msg.get("from", "peer")
                    sentiment = get_sentiment(text)
                    self._append("peer", f"{sender}: {text}  {sentiment}\n")
                elif action == "connect":
                    self.peer = msg.get("from", "")
                    self.state = S_CHATTING
                    self._append("system", f"Request from {self.peer}\n")
                    self._append("system", f"You are connected with {self.peer}. Chat away!\n")
                    self._update_status()
                elif action == "disconnect":
                    self._append("system", msg.get("msg", "Peer disconnected") + "\n")
                    self.state = S_LOGGEDIN
                    self.peer = ""
                    self._update_status()
            except Exception as e:
                self._append("system", f"Error: {e}\n")
        if self.running:
            self.root.after(100, self._process_queue)

    def _send_message(self):
        msg = self.msg_input.get().strip()
        if not msg:
            return
        self.msg_input.delete(0, tk.END)

        if self.state == S_CHATTING:
            sentiment = get_sentiment(msg)
            self._append("me", f"[{self.me}]: {msg}  {sentiment}\n")
            with self.sock_lock:
                mysend(self.s, json.dumps({"action": "exchange", "from": f"[{self.me}]", "message": msg}))
            if msg == "bye":
                with self.sock_lock:
                    mysend(self.s, json.dumps({"action": "disconnect"}))
                time.sleep(0.2)
                self.state = S_LOGGEDIN
                self.peer = ""
                self._update_status()

        elif msg.startswith("?"):
            term = msg[1:].strip()
            try:
                resp = self._send_cmd(json.dumps({"action": "search", "target": term}))
                result = resp.get("results", "").strip()
                if result:
                    self._append("system", result + "\n")
                else:
                    self._append("system", f"'{term}' not found\n")
            except:
                self._append("system", f"'{term}' not found\n")

        elif msg.startswith("p") and msg[1:].isdigit():
            try:
                resp = self._send_cmd(json.dumps({"action": "poem", "target": msg[1:]}))
                poem = resp.get("results", "").strip()
                if poem:
                    self._append("system", poem + "\n")
                else:
                    self._append("system", f"Sonnet {msg[1:]} not found.\n")
            except:
                self._append("system", f"Sonnet {msg[1:]} not found.\n")

        else:
            self._append("system", "Use the buttons above, or type:\n  ?term  → search\n  p#  → get sonnet\n")

    def _who(self):
        resp = self._send_cmd(json.dumps({"action": "list"}))
        self._append("system", "Users online:\n" + resp["results"] + "\n")

    def _time(self):
        resp = self._send_cmd(json.dumps({"action": "time"}))
        self._append("system", "Time is: " + resp["results"] + "\n")

    def _connect_peer(self):
        peer = simpledialog.askstring("Connect", "Enter username to connect to:", parent=self.root)
        if not peer:
            return
        resp = self._send_cmd(json.dumps({"action": "connect", "target": peer}))
        if resp["status"] == "success":
            self.peer = peer
            self.state = S_CHATTING
            self._append("system", f"Connected to {peer}. Chat away!\n")
            self._update_status()
        elif resp["status"] == "self":
            self._append("system", "Cannot connect to yourself!\n")
        elif resp["status"] == "busy":
            self._append("system", "User is busy, try again later.\n")
        else:
            self._append("system", "User is not online.\n")

    def _disconnect_peer(self):
        if self.state == S_CHATTING:
            with self.sock_lock:
                mysend(self.s, json.dumps({"action": "disconnect"}))
            self._append("system", f"Disconnected from {self.peer}.\n")
            self.state = S_LOGGEDIN
            self.peer = ""
            self._update_status()
        else:
            self._append("system", "You are not currently chatting.\n")

    def _ask_bot(self):
        msg = self.bot_input.get().strip()
        if not msg:
            return
        self.bot_input.delete(0, tk.END)
        self._append("me", f"[You → Bot]: {msg}\n")
        self._append("system", "Bot is thinking...\n")

        def run():
            try:
                reply = self.bot.chat(msg)
                self.root.after(0, self._append, "bot", f"[Bot]: {reply}\n")
            except Exception as e:
                self.root.after(0, self._append, "system", f"Bot error: {e}\n")

        threading.Thread(target=run, daemon=True).start()

    def _append(self, tag, msg):
        self.chat_display.config(state="normal")
        self.chat_display.insert(tk.END, msg if msg.endswith("\n") else msg + "\n", tag)
        self.chat_display.config(state="disabled")
        self.chat_display.see(tk.END)

    def _update_status(self):
        if self.state == S_CHATTING:
            self.status_var.set(f"Logged in as: {self.me}  |  Chatting with: {self.peer}")
        else:
            self.status_var.set(f"Logged in as: {self.me}  |  Not chatting")


def main():
    root = tk.Tk()
    ChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
