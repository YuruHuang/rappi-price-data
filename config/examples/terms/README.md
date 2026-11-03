# Complete original country terms

Each CSV contains the full original query list for its country and topic,
including generic, local, and brand searches. These are editable copies of the
default lists, not the short format examples in the parent directory.

Use `ar`, `co`, `pe`, or `mx` filenames to match the country you collect.
For example, from the project root on a Mac:

```zsh
mkdir -p inputs
cp config/examples/terms/co_beverages.csv inputs/my_beverage_terms.csv
open -e inputs/my_beverage_terms.csv
```

Keep the `term` header. Add or delete one query per row, then pass the copy with
`--beverage-terms-file inputs/my_beverage_terms.csv`. For tobacco, copy the
country's `_tobacco.csv` file and use `--tobacco-terms-file` instead.
Use new filenames if you already have edited copies you want to keep.

A supplied file replaces that topic's full list for the run. Keep all rows you
still want searched. Leave out term-file options to use the original defaults.
