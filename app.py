import os
from flask import Flask, request, abort



def retrievesheet():
	import gspread
	from oauth2client.client import GoogleCredentials as GC
	from gspread_dataframe import get_as_dataframe, set_with_dataframe
	from datetime import datetime
	import pandas as pd
	#gc = gspread.authorize(GC.get_application_default())
	from oauth2client.service_account import ServiceAccountCredentials
	scope = ['https://spreadsheets.google.com/feeds',
	'https://www.googleapis.com/auth/drive']
	credentials = ServiceAccountCredentials.from_json_keyfile_name('my_project.json', scope)
	gc = gspread.authorize(credentials)
	master_sh=gc.open_by_key("1vynkrJPMaXzAUxGS8bJIoiLZCQdAR9P7rKpholnA8yk")
	master_worksheet = master_sh.worksheet("Sheet1")
	dfkeys = pd.DataFrame(master_worksheet.get_all_values()[1:11])
	print(dfkeys.columns)


app = Flask(__name__)
@app.route('/', methods=['POST'])
def index():
	retrievesheet()
	print("123")
	if request.method == 'POST':
		print(request.json)
		return 'success', 200
	else:
		abort(400)
#57e0107c5767cc545a3e6d9480cbf411f57fe48a31cabe06f2bbb5250869
if __name__ == '__main__':
    #port = int(environ['PORT'], 5000))
	app.run()
