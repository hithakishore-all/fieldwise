# Contributing

Thanks for taking a look. Fieldwise is a portfolio prototype, so issues and small pull requests are welcome.

1. `make setup`, then `make test`. Everything should pass before and after your change.
2. Keep business rules in `app/services/` so the JSON API and the screens share them.
3. Add or update a test for any rule you change. Every acceptance criterion maps to a file in `tests/`.
4. Keep all data fictional. Use `.example` domains and invented names.
