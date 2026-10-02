"""
Turns a raw captured notification (package name + title + body text) into a
normalized transaction dict, or None if it doesn't look like a transaction
alert at all.

Tuned against real UBA and FCMB SMS debit/credit alerts, e.g.:

  UBA:
    Txn:DR
    Ac:2XX..26X
    Amt:NGN 10,200.00
    Des:POS Trf @ 22140HLY-OPay Chidex Obi Venture Ajerom
    Date:17-09-2026 08:35
    Bal:NGN 13,289.77

  FCMB:
    Dr Amt:NGN100,000.00
    AC: **4012
    DESC: |SMB1226657512|RPMT-FAST
    DT:11/09/26 18:22
    BAL:NGN37,675.21

Both banks label the amount as "Amt:" and mark direction either as a
separate "Txn:DR/CR" field (UBA) or attached directly to the amount as
"Dr Amt:"/"Cr Amt:" (FCMB) — so those two patterns are checked first, with
the older generic keyword-based guessing kept as a fallback for any other
bank/fintech that shows up later with an unrecognized format.
"""
