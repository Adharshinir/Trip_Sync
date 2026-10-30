
from flask import Flask, render_template, request, redirect, url_for, flash
import oracledb
import traceback

app = Flask(__name__)
app.secret_key = "tripsync-demo-secret"

# Change these details to match your Oracle connection.
DB_CONFIG = {
    "user": "SYSTEM",
    "password": "Darshinis@12",
    "host": "localhost",
    "port": 1521,
    "service_name": "FREEPDB1"
}


def get_connection():
    dsn = (
        f'{DB_CONFIG["host"]}:{DB_CONFIG["port"]}/'
        f'{DB_CONFIG["service_name"]}'
    )
    return oracledb.connect(
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        dsn=dsn
    )


# The 15 queries from your TripSync worksheet.
SQL_QUERIES = {
    1: {
        "title": "Trips with their owners",
        "concept": "INNER JOIN and ORDER BY",
        "sql": """SELECT t.trip_id, t.trip_name,
                  u.full_name AS trip_owner, t.start_date,
                  t.end_date, t.budget, t.status
                  FROM trips t
                  INNER JOIN users u ON t.user_id = u.user_id
                  ORDER BY t.trip_id"""
    },
    2: {
        "title": "Total expenses for each trip",
        "concept": "LEFT JOIN, SUM, NVL and GROUP BY",
        "sql": """SELECT t.trip_id, t.trip_name, t.budget,
                  NVL(SUM(e.amount), 0) AS total_expenses
                  FROM trips t
                  LEFT JOIN expenses e ON t.trip_id = e.trip_id
                  GROUP BY t.trip_id, t.trip_name, t.budget
                  ORDER BY t.trip_id"""
    },
    3: {
        "title": "Trips with a budget above average",
        "concept": "AVG and subquery",
        "sql": """SELECT trip_id, trip_name, budget
                  FROM trips
                  WHERE budget > (SELECT AVG(budget) FROM trips)
                  ORDER BY budget DESC"""
    },
    4: {
        "title": "Trips with no expenses recorded",
        "concept": "LEFT JOIN and IS NULL",
        "sql": """SELECT t.trip_id, t.trip_name, t.budget
                  FROM trips t
                  LEFT JOIN expenses e ON t.trip_id = e.trip_id
                  WHERE e.expense_id IS NULL
                  ORDER BY t.trip_id"""
    },
    5: {
        "title": "Spending by expense category",
        "concept": "COUNT, SUM, AVG and GROUP BY",
        "sql": """SELECT category, COUNT(*) AS number_of_expenses,
                  SUM(amount) AS total_spent,
                  ROUND(AVG(amount), 2) AS average_expense
                  FROM expenses
                  GROUP BY category
                  ORDER BY total_spent DESC"""
    },
    6: {
        "title": "Users who planned more than one trip",
        "concept": "JOIN, GROUP BY, HAVING and COUNT",
        "sql": """SELECT u.user_id, u.full_name,
                  COUNT(t.trip_id) AS total_trips
                  FROM users u
                  JOIN trips t ON u.user_id = t.user_id
                  GROUP BY u.user_id, u.full_name
                  HAVING COUNT(t.trip_id) > 1
                  ORDER BY total_trips DESC"""
    },
    7: {
        "title": "The most expensive expense",
        "concept": "MAX and subquery",
        "sql": """SELECT expense_id, trip_id, expense_name,
                  category, amount
                  FROM expenses
                  WHERE amount = (SELECT MAX(amount) FROM expenses)"""
    },
    8: {
        "title": "Destinations with trip names and owners",
        "concept": "JOIN across three tables",
        "sql": """SELECT d.destination_id, d.city, d.country,
                  t.trip_name, u.full_name AS trip_owner
                  FROM destinations d
                  JOIN trips t ON d.trip_id = t.trip_id
                  JOIN users u ON t.user_id = u.user_id
                  ORDER BY d.destination_id"""
    },
    9: {
        "title": "Trips with spending below ₹20,000",
        "concept": "SUM, GROUP BY and HAVING",
        "sql": """SELECT t.trip_id, t.trip_name,
                  u.full_name AS trip_owner,
                  SUM(e.amount) AS total_expenses
                  FROM trips t
                  JOIN users u ON t.user_id = u.user_id
                  JOIN expenses e ON t.trip_id = e.trip_id
                  GROUP BY t.trip_id, t.trip_name, u.full_name
                  HAVING SUM(e.amount) < 20000
                  ORDER BY total_expenses DESC"""
    },
    10: {
        "title": "Trips marked as PLANNED",
        "concept": "WHERE and ORDER BY",
        "sql": """SELECT t.trip_id, t.trip_name,
                  u.full_name AS trip_owner, t.budget, t.status
                  FROM trips t
                  JOIN users u ON t.user_id = u.user_id
                  WHERE t.status = 'PLANNED'
                  ORDER BY t.budget DESC"""
    },
    11: {
        "title": "Unique destination countries",
        "concept": "DISTINCT and ORDER BY",
        "sql": """SELECT DISTINCT country
                  FROM destinations
                  ORDER BY country"""
    },
    12: {
        "title": "Activities costing above average",
        "concept": "AVG and subquery",
        "sql": """SELECT activity_id, activity_name,
                  category, estimated_cost
                  FROM activities
                  WHERE estimated_cost >
                  (SELECT AVG(estimated_cost) FROM activities)
                  ORDER BY estimated_cost DESC"""
    },
    13: {
        "title": "Companions travelling on each trip",
        "concept": "Multiple JOINs",
        "sql": """SELECT t.trip_name, u.full_name AS trip_owner,
                  c.full_name AS companion_name,
                  c.email AS companion_email
                  FROM trips t
                  JOIN users u ON t.user_id = u.user_id
                  JOIN trip_companions tc ON t.trip_id = tc.trip_id
                  JOIN companions c ON tc.companion_id = c.companion_id
                  ORDER BY t.trip_id"""
    },
    14: {
        "title": "Activity count by category",
        "concept": "COUNT, SUM, GROUP BY and HAVING",
        "sql": """SELECT category, COUNT(*) AS total_activities,
                  SUM(estimated_cost) AS total_estimated_cost
                  FROM activities
                  GROUP BY category
                  HAVING COUNT(*) > 1
                  ORDER BY total_activities DESC"""
    },
    15: {
        "title": "Remaining budget for each trip",
        "concept": "LEFT JOIN, SUM, NVL and calculated column",
        "sql": """SELECT t.trip_id, t.trip_name, t.budget,
                  NVL(SUM(e.amount), 0) AS total_expenses,
                  t.budget - NVL(SUM(e.amount), 0) AS remaining_budget
                  FROM trips t
                  LEFT JOIN expenses e ON t.trip_id = e.trip_id
                  GROUP BY t.trip_id, t.trip_name, t.budget
                  ORDER BY remaining_budget DESC"""
    }
}


def read_dbms_output(cursor):
    """Read messages printed by a PL/SQL procedure."""
    lines = []
    line_var = cursor.var(str, size=32767)
    status_var = cursor.var(int)

    while True:
        cursor.callproc(
            "DBMS_OUTPUT.GET_LINE",
            [line_var, status_var]
        )
        if status_var.getvalue() != 0:
            break
        lines.append(line_var.getvalue() or "")

    return lines


def close_db(cursor, connection):
    if cursor is not None:
        cursor.close()
    if connection is not None:
        connection.close()


# ---------------- DASHBOARD ----------------
@app.route("/")
def home():
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM trips")
        trip_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM expenses")
        expense_count = cursor.fetchone()[0]

        cursor.execute("SELECT NVL(SUM(amount), 0) FROM expenses")
        total_expenses = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT t.trip_id, t.trip_name, u.full_name,
                   t.start_date, t.end_date, t.budget, t.status
            FROM trips t
            JOIN users u ON t.user_id = u.user_id
            ORDER BY t.trip_id DESC
            FETCH FIRST 5 ROWS ONLY
        """)
        recent_trips = cursor.fetchall()

        return render_template(
            "index.html",
            trip_count=trip_count,
            expense_count=expense_count,
            total_expenses=total_expenses,
            user_count=user_count,
            recent_trips=recent_trips
        )
    except Exception as error:
        traceback.print_exc()
        return f"Dashboard error: {error}", 500
    finally:
        close_db(cursor, connection)


# ---------------- TRIPS ----------------
@app.route("/trips")
def trips():
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT t.trip_id, t.trip_name, u.full_name,
                   t.start_date, t.end_date, t.budget, t.status
            FROM trips t
            JOIN users u ON t.user_id = u.user_id
            ORDER BY t.trip_id
        """)
        return render_template("trips.html", trips=cursor.fetchall())
    except Exception as error:
        traceback.print_exc()
        return f"Trips error: {error}", 500
    finally:
        close_db(cursor, connection)


# ---------------- EXPENSES ----------------
@app.route("/expenses")
def expenses():
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT e.expense_id, e.trip_id, t.trip_name,
                   e.expense_name, e.amount, e.expense_date, e.category
            FROM expenses e
            JOIN trips t ON e.trip_id = t.trip_id
            ORDER BY e.expense_id DESC
        """)
        all_expenses = cursor.fetchall()

        cursor.execute(
            "SELECT trip_id, trip_name FROM trips ORDER BY trip_id"
        )
        all_trips = cursor.fetchall()

        return render_template(
            "expenses.html",
            expenses=all_expenses,
            trips=all_trips
        )
    except Exception as error:
        traceback.print_exc()
        return f"Expenses page error: {error}", 500
    finally:
        close_db(cursor, connection)


# ---------------- ADD EXPENSE ----------------
@app.route("/expenses/add", methods=["POST"])
def add_expense():
    connection = cursor = None
    try:
        trip_id = int(request.form["trip_id"])
        expense_name = request.form["expense_name"].strip()
        amount = float(request.form["amount"])
        expense_date = request.form["expense_date"]
        category = request.form["category"].strip()

        if not expense_name or not category or amount < 0:
            flash("Enter valid expense details.", "error")
            return redirect(url_for("expenses"))

        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO expenses
                (trip_id, expense_name, amount, expense_date, category)
            VALUES
                (:trip_id, :expense_name, :amount,
                 TO_DATE(:expense_date, 'YYYY-MM-DD'), :category)
        """, {
            "trip_id": trip_id,
            "expense_name": expense_name,
            "amount": amount,
            "expense_date": expense_date,
            "category": category
        })
        connection.commit()
        flash("Expense added successfully!", "success")
    except Exception as error:
        traceback.print_exc()
        if connection:
            connection.rollback()
        flash(f"Could not add expense: {error}", "error")
    finally:
        close_db(cursor, connection)

    return redirect(url_for("expenses"))


# ---------------- UPDATE EXPENSE ----------------
@app.route("/expenses/update/<int:expense_id>", methods=["POST"])
def update_expense(expense_id):
    connection = cursor = None
    try:
        expense_name = request.form["expense_name"].strip()
        amount = float(request.form["amount"])
        category = request.form["category"].strip()
        expense_date = request.form["expense_date"]

        if not expense_name or not category or amount < 0:
            flash("Enter valid expense details.", "error")
            return redirect(url_for("expenses"))

        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            UPDATE expenses
            SET expense_name = :expense_name,
                amount = :amount,
                category = :category,
                expense_date = TO_DATE(:expense_date, 'YYYY-MM-DD')
            WHERE expense_id = :expense_id
        """, {
            "expense_name": expense_name,
            "amount": amount,
            "category": category,
            "expense_date": expense_date,
            "expense_id": expense_id
        })

        if cursor.rowcount == 0:
            connection.rollback()
            flash("Expense not found.", "error")
        else:
            connection.commit()
            flash("Expense updated successfully!", "success")
    except Exception as error:
        traceback.print_exc()
        if connection:
            connection.rollback()
        flash(f"Could not update expense: {error}", "error")
    finally:
        close_db(cursor, connection)

    return redirect(url_for("expenses"))


# ---------------- DELETE EXPENSE ----------------
@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):
    connection = cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM expenses WHERE expense_id = :expense_id",
            {"expense_id": expense_id}
        )

        if cursor.rowcount == 0:
            connection.rollback()
            flash("Expense not found.", "error")
        else:
            connection.commit()
            flash("Expense deleted successfully!", "success")
    except Exception as error:
        traceback.print_exc()
        if connection:
            connection.rollback()
        flash(f"Could not delete expense: {error}", "error")
    finally:
        close_db(cursor, connection)

    return redirect(url_for("expenses"))


# ---------------- 15 SQL QUERIES ----------------
@app.route("/queries")
def query_results():
    query_id = request.args.get("q", default=1, type=int)
    if query_id not in SQL_QUERIES:
        query_id = 1

    selected = SQL_QUERIES[query_id]
    connection = cursor = None
    rows, columns, error = [], [], None

    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(selected["sql"])
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    except Exception as exc:
        error = str(exc)
        traceback.print_exc()
    finally:
        close_db(cursor, connection)

    return render_template(
        "queries.html",
        query_id=query_id,
        selected=selected,
        query_list=SQL_QUERIES,
        columns=columns,
        rows=rows,
        error=error
    )


# ---------------- FUNCTIONS / PROCEDURES / CURSOR ----------------
@app.route("/plsql", methods=["GET", "POST"])
def plsql_demo():
    output_lines = []
    result_label = None
    result_value = None
    error = None
    connection = cursor = None

    if request.method == "POST":
        action = request.form.get("action", "")

        try:
            connection = get_connection()
            cursor = connection.cursor()

            if action == "total":
                trip_id = int(request.form["trip_id"])
                cursor.execute(
                    "SELECT get_total_trip_expense(:id) FROM dual",
                    {"id": trip_id}
                )
                result_value = cursor.fetchone()[0]
                result_label = f"Total expenses for Trip {trip_id}"

            elif action == "count":
                trip_id = int(request.form["trip_id"])
                cursor.execute(
                    "SELECT get_trip_expense_count(:id) FROM dual",
                    {"id": trip_id}
                )
                result_value = cursor.fetchone()[0]
                result_label = f"Expense count for Trip {trip_id}"

            elif action in ("cursor", "user_trips"):
                cursor.callproc("DBMS_OUTPUT.ENABLE")

                if action == "cursor":
                    trip_id = int(request.form["trip_id"])
                    cursor.callproc("DISPLAY_TRIP_EXPENSES", [trip_id])
                    result_label = (
                        f"DISPLAY_TRIP_EXPENSES output for Trip {trip_id}"
                    )
                else:
                    user_id = int(request.form["user_id"])
                    cursor.callproc("GET_USER_TRIPS", [user_id])
                    result_label = (
                        f"GET_USER_TRIPS output for User {user_id}"
                    )

                output_lines = read_dbms_output(cursor)
                if not output_lines:
                    output_lines = [
                        "The procedure ran but did not print any rows."
                    ]

            elif action == "add_expense":
                trip_id = int(request.form["trip_id"])
                expense_name = request.form["expense_name"].strip()
                amount = float(request.form["amount"])
                category = request.form["category"].strip()

                if not expense_name or not category or amount < 0:
                    raise ValueError("Enter valid expense details.")

                cursor.callproc(
                    "ADD_TRIP_EXPENSE",
                    [trip_id, expense_name, amount, category]
                )
                connection.commit()
                result_label = "ADD_TRIP_EXPENSE procedure"
                output_lines = read_dbms_output(cursor)

                if not output_lines:
                    output_lines = [
                        "Procedure called. Check Expenses and Audit History."
                    ]

            else:
                error = "Choose a demonstration."

        except Exception as exc:
            error = str(exc)
            traceback.print_exc()
            if connection:
                connection.rollback()
        finally:
            close_db(cursor, connection)

    return render_template(
        "plsql.html",
        output_lines=output_lines,
        result_label=result_label,
        result_value=result_value,
        error=error
    )


# ---------------- TRIGGER AUDIT HISTORY ----------------

@app.route("/audit")
def audit():
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT LOG_ID,
                   TABLE_NAME,
                   OPERATION,
                   RECORD_ID,
                   CHANGED_AT,
                   DETAILS
            FROM AUDIT_LOG
            ORDER BY LOG_ID DESC
        """)

        audit_logs = cursor.fetchall()

        return render_template(
            "audit.html",
            audit_logs=audit_logs
        )

    except Exception as e:
        return f"Audit page error: {e}", 500

    finally:
        cursor.close()
        conn.close()

# ---------------- DASHBOARD SQL FEATURES ----------------

DASHBOARD_FEATURES = {
    15: {
        "title": "Trip Budget Summary",
        "description": "View each trip's budget, total expenses and remaining balance.",
        "concept": "LEFT JOIN, SUM, NVL and calculated columns"
    },
    10: {
        "title": "Planned Trips",
        "description": "View trips that are currently marked as PLANNED.",
        "concept": "JOIN, WHERE and ORDER BY"
    },
    5: {
        "title": "Spending Analysis",
        "description": "Compare expense totals and average spending by category.",
        "concept": "COUNT, SUM, AVG and GROUP BY"
    },
    4: {
        "title": "Trips Without Expenses",
        "description": "Find trips that do not have any recorded expenses.",
        "concept": "LEFT JOIN and IS NULL"
    },
    13: {
        "title": "Travel Companions",
        "description": "View companions associated with each trip and its owner.",
        "concept": "JOIN across multiple tables"
    }
}


@app.route("/feature/<int:query_id>")
def dashboard_feature(query_id):
    # Only allow features configured for the dashboard.
    if query_id not in DASHBOARD_FEATURES:
        return "Dashboard feature not found.", 404

    feature = DASHBOARD_FEATURES[query_id]
    selected_query = SQL_QUERIES[query_id]

    connection = cursor = None
    rows = []
    columns = []
    error = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # Execute the real SQL query against Oracle.
        cursor.execute(selected_query["sql"])

        # Get column headings and result rows for the page.
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()

    except Exception as exc:
        error = str(exc)
        traceback.print_exc()

    finally:
        close_db(cursor, connection)

    return render_template(
        "feature_result.html",
        feature=feature,
        columns=columns,
        rows=rows,
        error=error
    )

if __name__ == "__main__":
    app.run(debug=True)