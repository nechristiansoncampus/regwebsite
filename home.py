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
    # add regwebsite@reg-website-341515.iam.gserviceaccount.com as editor to sheet
    sh = gc.open('2025 Spring Retreat - Responses & Planning')
    wks = sh.worksheet_by_title('Responses')

    if request.method == 'POST':
        i = 0
        for row in wks:
            i += 1
            sheet_pn = re.sub(r"\D", "", row[10]) #removes anything that's not a number
            form_pn = request.form['phone']
            print(sheet_pn, form_pn)
            if sheet_pn == form_pn:
                if (row[6].strip() == ''):
                    return render_template('not_paid.html', name=row[3] + ' ' + row[4])
                else:
                    wks.update_value('B' + str(i), True)
                    return render_template('info.html', name=row[3] + ' ' + row[4], group=row[11], housing=row[12])
                break
    return render_template('home.html', error="Phone number not registered")

# @app.route("/announcements", methods=['get'])
# def announcements():
#     gc = pygsheets.authorize(service_account_env_var='service_credentials')
#     sh = gc.open('2022 Spring Retreat - Registration & Planning')
#     wks = sh.worksheet_by_title('Announcements')

#     announcements = []
#     i = 0
#     for row in wks:
#         if i == 0:
#             i += 1
#             continue
#         announcements.append(row[0])
#         i += 1
#     return render_template('announcements.html', announcements=announcements)