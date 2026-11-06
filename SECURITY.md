# Security

Fieldwise is a portfolio prototype that runs on synthetic data. It is not hardened for production: the identity picker is a demo stand-in for real sign-in.

If you find a problem, please open a GitHub issue without exploit details, or contact the maintainer through GitHub and describe it privately.

What the prototype does enforce, and tests:
- identity from a signed server-side session only;
- role and ownership on every write;
- tenant scope on every read, with 404 and no title for other tenants;
- localhost-only binding by default;
- no secrets in the repository (`.env` is git-ignored).
