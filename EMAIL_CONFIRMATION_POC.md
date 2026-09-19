# Email Confirmation Proof of Concept

Confirmation email is disabled unless all three required SMTP settings exist:

```text
SMTP_HOST=smtp.gmail.com
SMTP_USERNAME=nechristiansoncampus@gmail.com
SMTP_APP_PASSWORD=<Google app password>
```

Optional settings:

```text
SMTP_PORT=587
SMTP_FROM=nechristiansoncampus@gmail.com
SMTP_FROM_NAME=NE Christians on Campus
SMTP_REPLY_TO=nechristiansoncampus@gmail.com
```

Use port `587` for STARTTLS or `465` for SMTP over SSL. Store the app password only
as a Render secret. Spaces in a Google-generated app password are ignored.

Email delivery runs on a two-thread background executor after the registration row is
saved. The app records confirmation status in two managed sheet columns:

- `Confirmation Email Status`
- `Confirmation Email Sent At`

The status moves from `Queued` to `Sent` or `Failed`. A queued or sent registration is
not submitted again with the same registration ID. Registration and payment remain
successful when email delivery fails. The failure is logged and marked in the sheet
for manual follow-up.

This executor is suitable for a proof of concept, but it is not a durable job queue. A
Render restart can interrupt a queued task before it runs. A production-grade version
should use a persistent worker or periodically retry stale `Queued` and `Failed` rows.
