# KOBIS Merge Rules

## Source files

- Put KOBIS period boxoffice files in `data/raw/`.
- Do not edit raw files.
- Rebuild `data/db/kobis_movies.db` with `src/scripts/build_kobis_sqlite.py`.

## Raw table

`boxoffice_period_raw` stores one row per movie row from each KOBIS file.

Extra metadata columns are added:

- `source_file`: source file name
- `period_start`: KOBIS query start date
- `period_end`: KOBIS query end date
- `loaded_at`: DB build timestamp
- `row_number_in_file`: row position inside the detected data table

## Movie identity

Movies are grouped by:

- `movie_name_clean`
- `release_date`

## Snapshot rule

`movie_snapshot` keeps one representative row per movie group.

Selection order:

1. Latest `period_end`
2. Highest `cumulative_audience`
3. Alphabetical `source_file`
4. Lowest `row_number_in_file`

## Target

`target_final_audience` is the maximum `cumulative_audience` within each
`movie_name_clean` + `release_date` group.
