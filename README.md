# AV Test API

A small Flask app for **testing write-back to the ArtsVision API**. It reads
events (the proven-working path, as in
[LabVision](https://github.com/ShowSysDan/LabVision)), lets you edit fields on a
selected event, and posts the changes back via ArtsVision's `SaveData`
operation — logging the full request/response so you can see exactly what the
server accepts or rejects.

## What it does

- **Settings** (stored in SQLite): API base URL, API key, SSL verification, and
  the read/write endpoint names. Includes a **Test connection** button that
  calls `GetEntityNames`.
- **Events**: query `GetData` for an event date range (+ optional status) and
  list the results.
- **Edit event**: shows a curated set of primary fields plus every other
  populated field. Only fields you actually change are sent.
- **Write**: builds a `SaveData` body — a single `ApiDataEntity` with one
  `RowState = 1` (Modified) row containing the event `Id` and changed fields —
  and POSTs it. The request, HTTP status, and response are shown and stored.
- **Write log**: every SaveData attempt, newest first.

## ArtsVision API (reference)

Base: `https://av2.artsvision.net/api`. Auth via the `apikey` header. All
responses are wrapped as `{"Status": 0|3, "Data": ...}` (3 = error, `Data` is
the message).

| Function        | Method   | Endpoint          |
|-----------------|----------|-------------------|
| GetEntityNames  | GET      | `getentitynames`  |
| GetMetadata     | GET      | `getmetadata`     |
| GetData         | GET/POST | `getdata`         |
| SaveData        | POST     | `savedata`        |

`SaveData` takes one `ApiDataEntity`:

```json
{
  "Entity": "Event",
  "Rows": [
    { "RowState": 1, "Data": { "Id": 211248, "Text for Calendar": "Updated" }, "Entities": null }
  ]
}
```

RowState: `0` None, `1` Modified, `2` Added, `3` Deleted. Only changed rows
should be included, and the entity must allow individual update
(`AllowIndividualUpdate` in its metadata).

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000, go to **Settings**, paste your API key, hit **Test
connection**, then load events and try a write.

The SQLite database (`avtest.db`) is created automatically on first run and is
git-ignored, as is any `.env`.

## Notes on the write test

- Start with a low-risk text field (e.g. `Text for Calendar`) on a test event.
- Field values are sent as strings from the form; typed fields (ints, dates)
  may need the value formatted to match the field type — the response will tell
  you if the server rejects it.
- Endpoint names and the "modified" RowState are configurable on the Settings
  page so you can adjust without code changes.
