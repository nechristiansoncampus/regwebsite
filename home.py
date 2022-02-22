from flask import Flask
from flask import render_template, request

import re

import pygsheets

app = Flask(__name__)

@app.route("/", methods=['post', 'get'])
def home():
    return render_template('home.html')

@app.route("/info", methods=['post', 'get'])
def info():
    gc = pygsheets.authorize(service_account_env_var='service_credentials')
    sh = gc.open('Testing Spreadsheet')
    wks = sh.worksheet_by_title('Responses')

    if request.method == 'POST':
        # print("post")
        # print(request.form)
        user = []
        i = 0
        for row in wks:
            i += 1
            # print(row[2], row[3], row[7].translate(str.maketrans('', '', '-')))
            sheet_pn = re.sub(r"\D", "", row[7])
            form_pn = request.form['phone']
            if sheet_pn == form_pn:
                # print(row[2], row[3])
                # print(row[7])
                if (row[4].strip() == ''):
                    return render_template('not_paid.html', name=row[2] + ' ' + row[3])
                else:
                    wks.update_value('B' + str(i), True)
                    return render_template('info.html', name=row[2] + ' ' + row[3])
                break
        # print(wks.get_row(i))
    return render_template('home.html', error="Phone number not registered")