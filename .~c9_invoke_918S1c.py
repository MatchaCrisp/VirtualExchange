import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # shows welcome message to username, for each owned stock, show avg bought price, number of shares owned, current price, unrealized gain, realized gain
    portfolio = db.execute("SELECT * FROM owned_stock WHERE user_id = ?",session["user_id"])

    # user cash and total
    cash = float(db.execute("SELECT cash FROM users WHERE id = ?;", session["user_id"])[0]["cash"])
    total = cash

    # add curr price into portfolio
    for ind, stock in enumerate(portfolio):
        curr = lookup(stock["symbol"])
        if not curr:
            portfolio[ind]["curr"] = 0
        else:
            portfolio[ind]["curr"] = curr["price"]
        portfolio[ind]["avg_price"] = float(stock["buy_tot"])/float(stock["num_shares"])
        portfolio[ind]["curr_val"] = float(curr["price"])*float(stock["num_shares"])
        total += portfolio[ind]["curr_val"]
        portfolio[ind]["unreal"] = float(portfolio[ind]["curr_val"]) - float(stock["buy_tot"])
        # remove user_id
        del(portfolio[ind]["user_id"])

    print(portfolio)
    # TODO:each row also has hyperlink to show detailed history
    # TODO:each row also has button to buy/sell
    return render_template("index.html", portfolio=portfolio, name=session["username"], cash=cash, total=total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # validate stock symbol, validate share number
        symbol = request.form.get("symbol").strip()
        shares = request.form.get("shares")

        if not shares or not shares.isdigit():
            return apology("INVALID SHARES")

        if not symbol:
            # invalid symbol/share num
            return apology("INVALID SYMBOL")

        shares = float(shares)
        stock_detail = lookup(symbol)

        if not stock_detail:
            # no such stock
            return apology("INVALID SYMBOL")


        # find user cash, validate purchase
        purchase_price = stock_detail["price"]*shares
        user_info = db.execute("SELECT * FROM users WHERE id LIKE ?", session["user_id"])
        if user_info[0]["cash"] < purchase_price:
            # insufficient funds
            return apology("INSUFFICIENT FUNDS")

        # update new balance in users, add row in purchase history, update portfolio in owned_stock
        db.execute("UPDATE users SET cash = ? WHERE id = ?;", user_info[0]["cash"] - purchase_price, session["user_id"])

        db.execute("INSERT INTO purchase_history (user_id, symbol, price, num_shares, purchase_time) VALUES(?, ?, ?, ?, datetime(\"now\"));",
                   session["user_id"], symbol, stock_detail["price"], shares)

        currStockPort = db.execute("SELECT * FROM owned_stock WHERE user_id = ? AND symbol = ?", session["user_id"], symbol)

        #case do not own stock
        if (len(currStockPort) == 0):
            db.execute("INSERT INTO owned_stock (user_id, symbol, buy_tot, num_shares, sold_tot, sold_shares) VALUES(?, ?, ?, ?, ?, ?)", session["user_id"], symbol, purchase_price, shares, 0, 0)
        #case own/owned stock
        else:
            newShares = currStockPort[0]["num_shares"]+shares
            newTot = currStockPort[0]["buy_tot"] + purchase_price
            db.execute("UPDATE owned_stock SET buy_tot = ?, num_shares = ? WHERE user_id = ? AND symbol = ?", newTot, newShares, session["user_id"], symbol)

        #return user to index (list of owned stocks)
        return redirect("/")
    #if via GET, show buy page
    return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    #return list of all transactions, sorted in date/time, displaying symbol, price, shares, buy/sell
    transacs = db.execute("SELECT symbol, ABS(price) as price, num_shares as shares, CASE WHEN price>0 THEN \"buy\" WHEN price<0 THEN \"sell\" ELSE \"INVALID\" END as action, -1*num_shares*price as change, TIME(purchase_time) as time, DATE(purchase_time) as date FROM purchase_history;")
    sortTran = {}

    for transac in transacs:
        if not(transac["date"] in sortTran):
            sortTran[transac["date"]]=[]

        sortTran[transac["date"]].append({
            "symbol":transac["symbol"],
            "price":transac["price"],
            "shares":transac["shares"],
            "action":transac["action"],
            "change":transac["change"],
            "time":transac["time"]
        })

    return render_template("history.html", sortTran = sortTran)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]
        session["username"] = rows[0]["username"]
        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        #look up stock via api, then if valid, return stats as a table
        symbol = request.form.get("symbol")
        if not symbol:
            #no symbol
            return apology("INVALID SYMBOL")

        stockData = lookup(symbol)
        if not stockData:
            #invalid symbol
            return apology("INVALID SYMBOL")

        return render_template("quote.html", stockData=stockData)
    #if via GET, return to lookup page
    return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """register user"""
    if request.method == "POST":
        #check validity of username/password, then if its existence in database, then add to users in finance.db, then return user to login
        newUser=request.form.get("username")
        newPw=request.form.get("password")
        newPwConf=request.form.get("confirmation")

        if not newUser or not newPw or not newPwConf or newPw != newPwConf:
            #invalid input
            return apology("INVALID USERNAME/PASSWORD")

        existence = db.execute("SELECT username FROM users where username LIKE ?", newUser)
        if len(existence) == 1:
            #username exists
            return apology("USERNAME ALREADY EXISTS")

        db.execute("INSERT INTO users (username, hash) VALUES(?,?)", newUser, generate_password_hash(newPw))

        return render_template("login.html")
    #else with GET, direct user to register.html
    return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    #sell page renders select menu of all owned stocks, validates symbol/number of shares, and sells at curr price
    #act of selling updates:
    #   cash in users
    #   new row in history
    #   num_shares, sold_shares, buy_tot, sold_tot in owned_stock
    if request.method == "POST":
        sellSymb = request.form.get("symbol")
        sellShare = request.form.get("shares")

        if not sellShare or not sellShare.isdigit():
            return apology("INVALID SHARE")
        if not sellSymb:
            return apology("INVALID SYMBOL")

        sellShare = float(sellShare)

        userStock = db.execute("SELECT * FROM owned_stock WHERE user_id = ? AND symbol = ?;", session["user_id"],sellSymb)

        #case of stock not owned
        if len(userStock) != 1:
            return apology("INVALID SYMBOL")

        #case of insufficient shares
        if userStock[0]["num_shares"] < sellShare:
            return apology("INVALID SHARE NUMBER")

        #get stock current info
        curr = lookup(sellSymb)

        #case of not existing stock
        if not curr:
            return apology("INVALID SYMBOL")

        #update user cash
        cash = float(db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"])
        currPrice = float(curr["price"])
        cash += currPrice * sellShare
        db.execute("UPDATE users SET cash = ? WHERE id = ?;", cash, session["user_id"])

        #add purchase_history
        db.execute("INSERT INTO purchase_history (symbol, price, num_shares, purchase_time) VALUES(?, ?, ?, DATETIME(\"now\"));",sellSymb, -currPrice, sellShare)

        #update owned_stock
        avgPrice = float(userStock[0]["buy_tot"]) / float(userStock[0]["num_shares"])
        sellTot = float(userStock[0]["sold_tot"]) + (currPrice - avgPrice) * sellShare
        newShareOwned = float(userStock[0]["num_shares"]) - sellShare
        newShareSold = float(userStock[0]["sold_shares"]) + sellShare
        buyTot = newShareOwned * avgPrice
        db.execute("UPDATE owned_stock SET sold_shares = ?, buy_tot = ?, sold_tot = ?, num_shares = ? WHERE user_id = ? AND symbol = ?;", newShareSold, buyTot, sellTot, newShareOwned, session["user_id"], sellSymb)

        #return user to porfolio
        return redirect("/")

    #if via GET return sell page with owned_stocks and their share num
    owned = db.execute("SELECT symbol, num_shares FROM owned_stock WHERE user_id = ? AND num_shares > 0;", session["user_id"])
    return render_template("sell.html", owned=owned)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
