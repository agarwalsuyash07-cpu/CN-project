#!/usr/bin/env bash
# Evidence 3: ONE mail to kapish with only an inline non-ASCII-named attachment,
# then the GUI opens already logged in as kapish.
source "$(dirname "$0")/_common.sh"

ATTACH_DIR="$ROOT/data/e3"
ATTACH="$ATTACH_DIR/रिपोर्ट_é.txt"

write_attachment() {
    mkdir -p "$ATTACH_DIR"
    cat >"$ATTACH" <<'EOF'
LocalMail — परियोजना रिपोर्ट / Project Report
==============================================

विषय (Subject): स्थानीय ईमेल स्थानांतरण प्रणाली
Course: BACSE203 Computer Networks, VIT
टीम (Team): Suyash, Kapish, Yashraj

सारांश (Summary)
----------------
यह फ़ाइल एक inline attachment के रूप में भेजी गई है, क्योंकि इसका आकार
1 MB से कम है। फ़ाइल का नाम देवनागरी और "é" अक्षर से बना है, ताकि यह
साबित हो सके कि RFC 2231 filename* encoding सही ढंग से काम करती है।

This file was sent as an inline MIME attachment because it is smaller than
1 MB. Its name mixes Devanagari and an accented Latin letter, which proves
that the RFC 2231 filename* parameter survives SMTP, the Maildir store,
POP3 retrieval and decoding on the receiving side.

मुख्य बिंदु (Key points)
-----------------------
1. SMTP सर्वर TCP पोर्ट 2525 पर चलता है।      SMTP server listens on TCP 2525.
2. POP3 सर्वर TCP पोर्ट 1110 पर चलता है।      POP3 server listens on TCP 1110.
3. बड़ी फ़ाइलें reference store (पोर्ट 8000) पर जाती हैं।
                                              Files of 1-10 MB go to the reference store.
4. 10-25 MB की फ़ाइलें 2 MB के टुकड़ों में भेजी जाती हैं।
                                              Files of 10-25 MB travel as 2 MB fragments.
5. हर फ़ाइल की SHA-256 जाँच होती है।           Every file is SHA-256 verified.

निष्कर्ष (Conclusion)
--------------------
यदि आप यह पाठ सही अक्षरों में पढ़ पा रहे हैं, तो UTF-8 सामग्री और गैर-ASCII
फ़ाइल नाम, दोनों ही बिना किसी त्रुटि के पहुँचे हैं।

If you can read this text with correct characters, both the UTF-8 content
and the non-ASCII filename arrived intact.

धन्यवाद! Thank you!
EOF
}

main() {
    title "EVIDENCE 3 — GUI inbox with an inline non-ASCII attachment"
    clean_state
    start_servers "$EVID/e3_server.log"
    write_attachment
    "$PY" -m localmail.client.cli send --user suyash --password "$(password_of suyash)" \
        --to kapish@localmail --subject "Evidence 3 — inline non-ASCII attachment" \
        --body $'Hi Kapish,\n\nthe project report is attached (Hindi + English).\n\n-- Suyash' \
        --attach "$ATTACH" 2>/dev/null
    echo
    echo "servers running (pid $(cat "$PIDFILE")), log: evidence/e3_server.log"
    echo "kapish has 1 message waiting: $(basename "$ATTACH") ($(wc -c <"$ATTACH" | tr -d ' ') bytes, inline)"
    cat <<'EOF'

The GUI opens now, already logged in as kapish. Then:
  1. click the mail "Evidence 3 — inline non-ASCII attachment" (TIER inline, ATT 1)
  2. click रिपोर्ट_é.txt in the Attachments list
  3. click Open -> the file opens in TextEdit
  4. click Save -> choose a folder -> the status bar shows "saved to ..."
  5. screenshot the GUI and TextEdit side by side
Close the GUI when done; stop the servers with scripts/evidence/stop_servers.sh
EOF
}

main 2>&1 | tee "$EVID/e3_prepare.txt"
exec "$PY" -m localmail.client.gui --user kapish --password "$(password_of kapish)"
