import threading

from ..common.lineio import log, setup_logging
from ..config import CONFIG
from .mailstore import MailStore
from .pop3_server import POP3Server
from .ref_store import RefStoreServer
from .smtp_server import SMTPServer


def start_all(cfg=None):
    cfg = cfg or CONFIG
    store = MailStore(cfg)
    smtp = SMTPServer(cfg, store)
    pop3 = POP3Server(cfg, store)
    ref = RefStoreServer(cfg)
    smtp.start()
    pop3.start()
    ref.start()
    return store, smtp, pop3, ref


def main():
    setup_logging()
    cfg = CONFIG
    store, smtp, pop3, ref = start_all(cfg)
    host = cfg["host"]
    log.info("[BOOT] SMTP tcp/%d  POP3 tcp/%d  refstore http://%s:%d/ref  bound on %s",
             smtp.port, pop3.port, host, ref.port, host)
    log.info("[BOOT] domain=%s users=%s data=%s",
             cfg["domain"], ",".join(sorted(cfg["users"])), store.root)
    log.info("[BOOT] Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        log.info("[BOOT] shutting down")
    finally:
        smtp.stop()
        pop3.stop()
        ref.stop()


if __name__ == "__main__":
    main()
