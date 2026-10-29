#!/usr/bin/env bash
# Stops the servers left running by e2_pop3_prepare.sh / e3_gui_prepare.sh.
source "$(dirname "$0")/_common.sh"
stop_servers
echo "LocalMail servers stopped."
