# Report traceability checklist

> **Item wording is rebuilt, not copied.** The original build prompt's 15 items are not saved in
> the repo. This list is rebuilt from the build plan, which tagged each phase with its checklist
> number. Check each line against the report's own wording before pasting.

Proof columns name a test in `tests/` (run: `python3 -m unittest discover -v`, 102 tests, all OK
on 2026-10-30) or a script in `scripts/evidence/`.

| # | Item | Status | Proof |
|---|---|---|---|
| 1 | Own SMTP server on raw TCP sockets, port 2525; own socket clients (no smtplib/poplib outside `tests/`) | done | `test_smtp.TestSMTPSession.test_full_exchange_exact_strings`, `test_reference_clients.TestReferenceClients.test_smtplib_delivers`; E1 `e1_smtp_wireshark.sh` |
| 2 | SMTP command sequence enforced: 503 bad sequence, 501 syntax, 500 unknown | done | `test_smtp.TestSMTPSession.test_bad_sequence_503`, `test_unknown_command_500_and_syntax_501` |
| 3 | Exact reply strings (220/250/354/221/550/552) and `[SMTP]`/`[POP3]`/`[HTTP]` C:/S: logging, password masked as `PASS ****` | done | `test_smtp.TestSMTPSession.test_full_exchange_exact_strings`, `test_unknown_user_550`, `test_smtp.TestSMTPOversize.test_oversize_552`, `test_pop3.TestPasswordNotLogged.test_log_masks_pass_and_never_contains_a_password` |
| 4 | Maildir storage (tmp→new rename), SQLite index, per-user lock (`store_with_lock`) | done | `test_smtp.TestStorage.test_maildir_layout_and_index_row`, `test_concurrency.TestConcurrentDelivery.test_twenty_threads_into_one_mailbox` |
| 5 | POP3 server on 1110: AUTHORIZATION→TRANSACTION→UPDATE, STAT/LIST/RETR/DELE/QUIT/UIDL, DELE committed only at QUIT, one session per mailbox | done | `test_pop3.TestPOP3Deletes.test_dele_only_marks_until_quit`, `test_dropped_connection_after_dele_deletes_nothing`, `test_pop3.TestPOP3Locking.test_one_session_per_mailbox`; E2 `e2_pop3_prepare.sh` |
| 6 | MIME: multipart/mixed, text/plain first, octet-stream + base64 attachments, RFC 2231 non-ASCII filenames | done | `test_mime.TestMIME.test_every_attachment_is_octet_stream_base64_attachment`, `test_rfc2231_used_for_non_ascii_filename`, `test_non_ascii_filename_and_subject_round_trip`; E3 `e3_gui_prepare.sh` |
| 7 | Inline tier: ≤ 1 MB (raw bytes) sent as a MIME attachment | done | `test_tiering.TestTierBoundaries.test_small_sizes_are_inline`, `test_tiering.TestTierTransfers.test_inline_mail_carries_the_bytes`, `test_inline_non_ascii_round_trip` |
| 8 | Reference tier: 1–10 MB uploaded with HTTP PUT to the store on 8000, mail carries X-Ref-* headers only, GET + SHA-256 check on receipt | done | `test_tiering.TestTierTransfers.test_reference_mail_has_headers_and_no_attachment_bytes`, `test_reference_downloaded_and_hash_verified`, `test_reference_hash_mismatch_is_not_saved`, `test_refstore.TestRefStore.test_put_get_round_trip` |
| 9 | Fragment tier: 10–25 MB split into 2 MB mails, reassembled by X-Fragment-ID/Index, SHA-256 verified, one inbox row; > 25 MB rejected | done | `test_tiering.TestTierTransfers.test_fragments_reassemble_into_one_logical_message`, `test_tiering.TestFragmentEdgeCases.test_out_of_order_fragments_reassemble`, `test_missing_fragment_reports_incomplete_and_saves_nothing`, `test_corrupted_fragment_fails_sha256_and_is_not_saved`, `test_tiering.TestTierBoundaries.test_reject_raises`; E4 `e4_fragment_demo.sh` |
| 10 | Concurrency: thread per connection, one store call per recipient, `rcpts` reset after DATA | done | `test_concurrency.TestConcurrentDelivery.test_twenty_threads_into_one_mailbox`, `test_smtp.TestStorage.test_one_store_call_per_recipient`, `test_smtp.TestSMTPSession.test_rcpts_reset_after_data` |
| 11 | Tkinter GUI: login, inbox (from/subject/date/tier/fragments/attachments/status), Open, Save, Compose with tier preview | done | `test_gui.TestInboxDateColumn.*`, `test_gui.TestOpenAndSave.*`, `test_gui.TestOpenWithOS.*`; E3 `e3_gui_prepare.sh` — the auto-login and the full column layout were checked on 2026-09-30 |
| 12 | Single-host and LAN mode (`--host`, bind address, 192.168.1.x layout) | done, **not verified on a real LAN** | README §4; client `--host` in `cli.py` and `gui.py` |
| 13 | CLI `send` / `fetch [--delete]` and a unittest suite | done | `test_tiering.TestDeletePolicy.*` (the `--delete` hold policy); E5 `e5_tests.sh` |
| 14 | Evidence screenshots E1–E5 | done — E1–E5 captured on the Ubuntu 24.04 test machine (Wireshark 4.2.2) | `screenshots/review2/E1a`–`E5*.png`, `scripts/evidence/`, [EVIDENCE.md](../EVIDENCE.md) |
| 15 | Real code extracts for report section 6.3 (< 40 lines) | done | `evidence/section_6_3_extracts.txt` (37 code lines), written by `scripts/evidence/make_report_material.sh` |
