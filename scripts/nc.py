"""Minimal netcat for hand-typed SMTP/POP3 sessions on Windows, which ships without nc.

    python scripts/nc.py localhost 1110

Each typed line goes out with CRLF, like a real mail client (same as `nc -c`); replies are
printed byte-for-byte as they arrive. Exits when the server closes the connection.
"""
import os
import socket
import sys
import threading


def pump(sock):
    while data := sock.recv(4096):
        sys.stdout.buffer.write(data)
        sys.stdout.flush()
    os._exit(0)   # server closed (e.g. after QUIT): don't wait for another typed line


def main(argv=None):
    host, port = (argv or sys.argv[1:])[:2]
    sock = socket.create_connection((host, int(port)))
    reader = threading.Thread(target=pump, args=(sock,))
    reader.start()
    for line in sys.stdin:
        sock.sendall(line.rstrip("\r\n").encode("utf-8") + b"\r\n")
    sock.shutdown(socket.SHUT_WR)   # stdin ended: let the server see EOF, then drain replies
    reader.join()


if __name__ == "__main__":
    main()
