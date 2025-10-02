import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import socket
import threading
import os
from pathlib import Path

# ==============================================================================
# P2P SERVER LOGIC (Handles incoming requests) - NO CHANGES HERE
# ==============================================================================

class P2PServer:
    """
    The server component that runs on each peer. It listens for connections
    and handles requests for searching, downloading, and registering files.
    """
    def __init__(self, host='0.0.0.0', port=5000, status_callback=None):
        self.host = host
        self.port = port
        self.server_socket = None
        self.running = False
        # Stores registered files as: {'filename.ext': '/path/to/filename.ext'}
        self.registered_files = {}
        self.status_callback = status_callback

    def log(self, message):
        """Logs a message using the provided UI callback."""
        if self.status_callback:
            self.status_callback(message)

    def start(self):
        """Starts the P2P server in a separate thread."""
        if self.running:
            return True

        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.log(f"✅ Server started, listening on {socket.gethostbyname(socket.gethostname())}:{self.port}")

            server_thread = threading.Thread(target=self.listen_for_connections, daemon=True)
            server_thread.start()
            return True
        except Exception as e:
            self.log(f"❌ Server Error: {e}")
            self.running = False
            return False

    def stop(self):
        """Stops the P2P server."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        self.log("🛑 Server stopped.")

    def listen_for_connections(self):
        """Listens for incoming peer connections."""
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                self.log(f"🔗 Accepted connection from {addr[0]}:{addr[1]}")
                client_thread = threading.Thread(target=self.handle_client, args=(client_socket, addr), daemon=True)
                client_thread.start()
            except OSError:
                if self.running:
                    self.log("❌ Connection listening error.")
                break # Exit loop if socket is closed

    def handle_client(self, client_socket, addr):
        """Handles a single client's request."""
        try:
            data = client_socket.recv(1024).decode('utf-8')
            parts = data.split('|')
            command = parts[0]
            
            if command == "SEARCH" and len(parts) > 1:
                filename = parts[1]
                self.search_file(client_socket, filename)
            elif command == "DOWNLOAD" and len(parts) > 1:
                filename = parts[1]
                self.send_file(client_socket, filename)
            else:
                client_socket.send("Invalid command".encode('utf-8'))
        except Exception as e:
            self.log(f"⚠️ Error handling client {addr[0]}: {e}")
        finally:
            client_socket.close()

    def search_file(self, client_socket, filename):
        """Searches for a file in the registered files list."""
        if filename in self.registered_files:
            client_socket.send(f"FOUND|{filename}".encode('utf-8'))
            self.log(f"🔍 Search hit for '{filename}'")
        else:
            client_socket.send("NOT_FOUND".encode('utf-8'))

    def send_file(self, client_socket, filename):
        """Sends a requested file to a peer."""
        filepath = self.registered_files.get(filename)
        
        if not filepath or not os.path.isfile(filepath):
            client_socket.send("FILE_NOT_FOUND".encode('utf-8'))
            return
        
        try:
            file_size = os.path.getsize(filepath)
            client_socket.send(f"FILE_FOUND|{file_size}".encode('utf-8'))
            
            response = client_socket.recv(1024).decode('utf-8')
            if response != "READY":
                return
            
            self.log(f"🚀 Sending '{filename}' ({file_size} bytes)...")
            with open(filepath, 'rb') as f:
                while chunk := f.read(4096):
                    client_socket.send(chunk)
            self.log(f"✅ Successfully sent '{filename}'.")
        except Exception as e:
            self.log(f"❌ Error sending file: {e}")

    def register_file(self, filepath):
        """Registers a file, making it available for sharing."""
        if not os.path.isfile(filepath):
            self.log(f"❌ Cannot register. File not found: {filepath}")
            return
        filename = os.path.basename(filepath)
        self.registered_files[filename] = filepath
        self.log(f"📂 Registered: '{filename}'")

# ==============================================================================
# P2P CLIENT LOGIC (Sends requests to other peers) - NO CHANGES HERE
# ==============================================================================
class P2PClient:
    """
    The client component that connects to other peers to search
    for and download files.
    """
    def __init__(self, download_dir='downloads', status_callback=None):
        self.download_dir = download_dir
        self.status_callback = status_callback
        Path(self.download_dir).mkdir(exist_ok=True)

    def log(self, message):
        """Logs a message using the provided UI callback."""
        if self.status_callback:
            self.status_callback(message)

    def connect_to_peer(self, peer_host, peer_port):
        """Establishes a connection with a peer."""
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((peer_host, peer_port))
            return client_socket
        except ConnectionRefusedError:
            self.log(f"❌ Connection refused by {peer_host}:{peer_port}")
            return None
        except Exception as e:
            self.log(f"❌ Error connecting to peer: {e}")
            return None

    def search_file(self, peer_host, peer_port, filename):
        """Searches for a file on a specific peer."""
        client_socket = self.connect_to_peer(peer_host, peer_port)
        if not client_socket:
            return "CONNECTION_ERROR"
        
        try:
            client_socket.send(f"SEARCH|{filename}".encode('utf-8'))
            response = client_socket.recv(1024).decode('utf-8')
            return response
        finally:
            client_socket.close()

    def download_file(self, peer_host, peer_port, filename, progress_callback=None):
        """Downloads a file from a specific peer."""
        client_socket = self.connect_to_peer(peer_host, peer_port)
        if not client_socket:
            return "CONNECTION_ERROR"
        
        try:
            client_socket.send(f"DOWNLOAD|{filename}".encode('utf-8'))
            response = client_socket.recv(1024).decode('utf-8')
            
            if response.startswith("FILE_FOUND"):
                _, file_size_str = response.split('|')
                file_size = int(file_size_str)
                
                client_socket.send("READY".encode('utf-8'))
                
                filepath = os.path.join(self.download_dir, filename)
                received_data = 0
                
                with open(filepath, 'wb') as f:
                    while received_data < file_size:
                        data = client_socket.recv(4096)
                        if not data:
                            break
                        f.write(data)
                        received_data += len(data)
                        
                        if progress_callback:
                            progress = min((received_data / file_size) * 100, 100)
                            progress_callback(progress)
                
                return "SUCCESS"
            else:
                return "FILE_NOT_FOUND"
        except Exception as e:
            return f"ERROR: {str(e)}"
        finally:
            client_socket.close()

# ==============================================================================
# GUI APPLICATION - MODIFICATIONS HERE
# ==============================================================================
class P2PFileTransferApp:
    """The main Tkinter GUI for the P2P application."""
    def __init__(self, root):
        self.root = root
        self.root.title("P2P File Transfer")
        self.root.geometry("650x550") # Increased height for progress bar
        self.root.configure(bg="#121212")

        # Backend components
        self.server = P2PServer(status_callback=self.update_status)
        self.client = P2PClient(status_callback=self.update_status)
        
        # Start the server automatically
        if not self.server.start():
            messagebox.showerror("Server Error", "Could not start the P2P server. The port might be in use.")
            self.root.destroy()
            return
        
        self.create_widgets()

    def create_widgets(self):
        # --- Styles ---
        label_style = {"bg": "#121212", "fg": "#CCCCCC", "font": ("Arial", 11)}
        entry_style = {"bg": "#1E1E1E", "fg": "white", "insertbackground": "white", "relief": "flat"}
        button_style = {"font": ("Arial", 11, "bold"), "fg": "white", "activebackground": "#444", 
                        "activeforeground": "white", "relief": "flat", "bd": 0, "width": 15, "pady": 5}

        # --- Title ---
        title_label = tk.Label(self.root, text="P2P File Transfer - Reg No: 24BCE5455 & 24BCE1526",
                               font=("Arial", 16, "bold"), bg="#121212", fg="#5A5C5B")
        title_label.pack(pady=20)

        # --- Peer and File Input Frame ---
        input_frame = tk.Frame(self.root, bg="#121212")
        input_frame.pack(pady=10, padx=20, fill="x")

        tk.Label(input_frame, text="Peer Address (host:port):", **label_style).grid(row=0, column=0, sticky="w", pady=2)
        self.peer_entry = tk.Entry(input_frame, width=40, **entry_style)
        self.peer_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        self.peer_entry.insert(0, "127.0.0.1:5000")

        tk.Label(input_frame, text="File to Register / Search / Download:", **label_style).grid(row=2, column=0, sticky="w", pady=(10, 2))
        self.file_entry = tk.Entry(input_frame, width=35, **entry_style)
        self.file_entry.grid(row=3, column=0, sticky="ew", pady=2)
        
        #browse_btn = tk.Button(input_frame, text="📂 Browse", command=self.browse_file, bg="#444444", **button_style, width=10)
        # CORRECTED CODE
        browse_style = button_style.copy() # Make a copy of the main style
        browse_style['width'] = 10         # Set the desired width in the copy

        browse_btn = tk.Button(input_frame, text="📂 Browse", command=self.browse_file, bg="#444444", **browse_style)
        browse_btn.grid(row=3, column=1, sticky="ew", padx=(5,0), pady=2)

        input_frame.grid_columnconfigure(0, weight=1)

        # --- Action Buttons Frame ---
        btn_frame = tk.Frame(self.root, bg="#121212")
        btn_frame.pack(pady=15)

        tk.Button(btn_frame, text="⬆ Register File", command=self.register_file_action, bg="#2980b9", **button_style).grid(row=0, column=0, padx=10)
        tk.Button(btn_frame, text="🔎 Search File", command=self.search_file_action, bg="#27ae60", **button_style).grid(row=0, column=1, padx=10)
        tk.Button(btn_frame, text="⬇ Download File", command=self.download_file_action, bg="#f39c12", **button_style).grid(row=0, column=2, padx=10)

        # --- Progress Bar Frame (Initially hidden) ---
        self.progress_frame = tk.Frame(self.root, bg="#121212")
        self.progress_frame.pack(pady=5, padx=20, fill="x")
        
        self.progress_label = tk.Label(self.progress_frame, text="Downloading...", **label_style)
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", length=100, mode="determinate")
        
        # Initially hide the progress bar and its label
        self.progress_label.pack_forget()
        self.progress_bar.pack_forget()

        # --- Status Box ---
        self.status_text = tk.Text(self.root, height=12, width=70, bg="#1E1E1E", fg="#00FFAA",
                                   font=("Consolas", 10), insertbackground="white", relief="flat")
        self.status_text.pack(pady=10, padx=20, fill="both", expand=True)

    def browse_file(self):
        filepath = filedialog.askopenfilename(title="Select a File")
        if filepath:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, filepath)

    def parse_peer_address(self):
        peer_addr = self.peer_entry.get().strip()
        if ":" not in peer_addr:
            messagebox.showwarning("Invalid Address", "Please enter the peer address in 'host:port' format.")
            return None, None
        
        try:
            host, port_str = peer_addr.split(":")
            port = int(port_str)
            return host, port
        except ValueError:
            messagebox.showwarning("Invalid Port", "The port must be a number.")
            return None, None

    def register_file_action(self):
        filepath = self.file_entry.get().strip()
        if not filepath:
            messagebox.showwarning("No File", "Please enter or browse for a file to register.")
            return
        if not os.path.isfile(filepath):
             messagebox.showerror("File Not Found", f"The file '{filepath}' does not exist.")
             return
        
        self.server.register_file(filepath)

    def search_file_action(self):
        host, port = self.parse_peer_address()
        if not host:
            return
            
        filepath = self.file_entry.get().strip()
        if not filepath:
            messagebox.showwarning("No Filename", "Please enter a filename to search for.")
            return
        filename = os.path.basename(filepath)

        self.update_status(f"🔎 Searching for '{filename}' on {host}:{port}...")
        
        def do_search():
            result = self.client.search_file(host, port, filename)
            if result == "CONNECTION_ERROR":
                self.update_status(f"❌ Connection error while searching.")
            elif result.startswith("FOUND"):
                self.update_status(f"✅ File '{filename}' found on peer {host}:{port}.")
            else:
                self.update_status(f"🚫 File '{filename}' not found on peer {host}:{port}.")
        
        threading.Thread(target=do_search, daemon=True).start()

    def download_file_action(self):
        """Action for the 'Download File' button. Runs in a thread."""
        host, port = self.parse_peer_address()
        if not host: return
            
        filepath = self.file_entry.get().strip()
        if not filepath:
            messagebox.showwarning("No Filename", "Please enter a filename to download.")
            return
        filename = os.path.basename(filepath)

        # Show and reset the progress bar
        self.progress_label.config(text=f"Downloading {filename}...")
        self.progress_label.pack(fill="x")
        self.progress_bar.pack(fill="x", expand=True)
        self.progress_bar["value"] = 0
        self.root.update_idletasks()

        def do_download():
            def update_progress_bar(progress):
                """Callback function to update the progress bar from the download thread."""
                self.progress_bar["value"] = progress
                self.root.update_idletasks() # Force UI update
            
            self.update_status(f"⬇️ Requesting to download '{filename}' from {host}:{port}...")
            result = self.client.download_file(host, port, filename, update_progress_bar)
            
            # Use root.after to ensure UI updates are done in the main thread
            def final_update():
                # Hide the progress bar
                self.progress_label.pack_forget()
                self.progress_bar.pack_forget()
                
                if result == "SUCCESS":
                    self.update_status(f"✅ Successfully downloaded '{filename}' to the 'downloads' folder.")
                elif result == "CONNECTION_ERROR":
                    self.update_status(f"❌ Connection error during download.")
                elif result == "FILE_NOT_FOUND":
                     self.update_status(f"🚫 File '{filename}' is no longer available on peer {host}:{port}.")
                else:
                    self.update_status(f"❌ Download error: {result}")
            
            self.root.after(100, final_update) # Schedule the final update

        threading.Thread(target=do_download, daemon=True).start()

    def update_status(self, message):
        """Appends a message to the status text box on the main thread."""
        def append():
            self.status_text.insert(tk.END, message + "\n")
            self.status_text.see(tk.END)
        self.root.after(0, append)

    def on_closing(self):
        """Handles the window closing event."""
        self.server.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = P2PFileTransferApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()