"""AV Test API — read ArtsVision events, edit fields, test writing back.

A deliberately small Flask app whose purpose is to exercise a write-back to the
ArtsVision API. It reads events (proven to work in LabVision), presents editable
fields per selected event, and posts changed fields back to a configurable write
endpoint while logging the full request/response for inspection.
"""

import json
import os
from datetime import date, datetime, timedelta

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

import av_client
import config
import db

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY

db.init_db()


# --- Template helpers --------------------------------------------------------

@app.template_filter("prettyjson")
def prettyjson(value):
    try:
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def _fmt_date(value):
    """Render an ISO-ish AV datetime string as a friendly date/time."""
    if not value or not isinstance(value, str):
        return value
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value[:19], fmt)
            # AV uses a 1900-01-01 sentinel date for time-only fields.
            if dt.year == 1900:
                return dt.strftime("%I:%M %p").lstrip("0")
            return dt.strftime("%b %d, %Y")
        except ValueError:
            continue
    return value


app.jinja_env.filters["fmtdate"] = _fmt_date


# --- Routes ------------------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("events"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        keys = [
            "api_base_url",
            "api_key",
            "read_endpoint",
            "write_endpoint",
            "write_row_state",
            "default_entity",
            "default_event_status",
        ]
        values = {k: request.form.get(k, "").strip() for k in keys}
        values["ssl_verify"] = "1" if request.form.get("ssl_verify") == "on" else "0"
        db.update_settings(values)
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", settings=db.get_settings())


@app.route("/settings/test")
def test_connection():
    try:
        names = av_client.get_entity_names()
        flash(
            f"Connected. GetEntityNames returned {len(names)} entities "
            f"(e.g. {', '.join(names[:5])}).",
            "success",
        )
    except av_client.AVError as exc:
        flash(f"Connection failed: {exc}", "error")
    return redirect(url_for("settings"))


@app.route("/events")
def events():
    settings = db.get_settings()
    today = date.today()
    date_from = request.args.get("from") or today.strftime("%m/%d/%Y")
    date_to = request.args.get("to") or (today + timedelta(days=1)).strftime("%m/%d/%Y")
    status = request.args.get("status", settings.get("default_event_status", ""))

    rows, error = [], None
    if request.args.get("go"):
        try:
            rows = av_client.get_events(date_from, date_to, status or None)
        except av_client.AVError as exc:
            error = str(exc)

    return render_template(
        "events.html",
        rows=rows,
        error=error,
        date_from=date_from,
        date_to=date_to,
        status=status,
        searched=bool(request.args.get("go")),
    )


@app.route("/events/<int:event_id>/edit")
def edit_event(event_id):
    try:
        event = av_client.get_event(event_id)
    except av_client.AVError as exc:
        flash(str(exc), "error")
        return redirect(url_for("events"))
    if not event:
        flash(f"Event {event_id} not found.", "error")
        return redirect(url_for("events"))

    curated = [f for f in config.CURATED_FIELDS if f in event]
    # Any populated field that isn't already curated, for the "all fields" area.
    other_populated = sorted(
        k for k, v in event.items()
        if k not in curated and v not in (None, "") and k not in ("Id", "Event Id")
    )
    return render_template(
        "edit_event.html",
        event=event,
        event_id=event_id,
        curated=curated,
        other_populated=other_populated,
    )


@app.route("/events/<int:event_id>/write", methods=["POST"])
def write_event(event_id):
    # The form posts original_<field> and value_<field> pairs; we only send
    # fields whose value actually changed.
    changes = {}
    for key in request.form:
        if not key.startswith("value_"):
            continue
        field = key[len("value_"):]
        new_value = request.form.get(key, "")
        original = request.form.get("original_" + field, "")
        if new_value != original:
            changes[field] = new_value

    if not changes:
        flash("No fields were changed — nothing to write.", "error")
        return redirect(url_for("edit_event", event_id=event_id))

    result = av_client.write_event(event_id, changes)
    db.log_writeback(
        ts=datetime.now().isoformat(timespec="seconds"),
        event_id=str(event_id),
        endpoint=result.get("endpoint"),
        request_json=json.dumps(result.get("request"), default=str),
        response_status=result.get("status"),
        response_body=json.dumps(result.get("body"), default=str),
        ok=result.get("ok"),
    )
    if result.get("ok"):
        flash(f"Write accepted by AV (HTTP {result.get('status')}).", "success")
    else:
        flash(
            f"Write did NOT succeed (HTTP {result.get('status')}). "
            "See the response below and the Logs page.",
            "error",
        )
    return render_template(
        "write_result.html",
        event_id=event_id,
        changes=changes,
        result=result,
    )


@app.route("/metadata")
def metadata():
    start = request.args.get("entity", "").strip() or None
    entities, error = [], None
    if request.args.get("go"):
        try:
            entities = av_client.get_metadata(start_entity=start)
        except av_client.AVError as exc:
            error = str(exc)
    return render_template(
        "metadata.html",
        entities=entities,
        error=error,
        start=start or "",
        searched=bool(request.args.get("go")),
    )


@app.route("/logs")
def logs():
    return render_template("logs.html", logs=db.get_writeback_logs())


if __name__ == "__main__":
    # Host/port are configurable via env vars. Default binds to 0.0.0.0 (all
    # network interfaces); set AVTEST_HOST=127.0.0.1 to restrict to localhost.
    host = os.environ.get("AVTEST_HOST", "0.0.0.0")
    port = int(os.environ.get("AVTEST_PORT", "7070"))
    # Debug defaults OFF: with the app reachable on the network, Flask's debug
    # reloader/debugger is a remote-code-execution risk. Set AVTEST_DEBUG=1 to
    # enable it for local development only.
    debug = os.environ.get("AVTEST_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
