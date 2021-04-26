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

	print(dfkeys.columns)
	if 'contact_id' in webhook_json.keys():
		contact_id = webhook_json['contact_id']
	else: 
		contact_id = ''
	if 'full_name' in webhook_json.keys():
		full_name = webhook_json['full_name']
	else: 
		full_name = ''
	if 'email' in webhook_json.keys():
		email = webhook_json['email']
	else: 
		email = ''
	if 'tags' in webhook_json.keys():
		tags = ','.join([s for s in webhook_json['tags']]) if isinstance(webhook_json['tags'], list) else webhook_json['tags']
	else: 
		tags = ''
	if 'phone' in webhook_json.keys():
		phone = webhook_json['phone']
	else: 
		phone = ''
	if 'location' in webhook_json.keys():
		location_name = webhook_json['location']['name']
		location_id = webhook_json['location']['id']
	else: 
		location_name = ''
		location_id = ''
	if 'date_created' in webhook_json.keys():
		date_created = webhook_json['date_created']
	else: 
		date_created = '
	if 'message' in webhook_json.keys():
		message = BeautifulSoup(webhook_json['message']['body']).find('div',{"dir":"ltr"}).text
	else: 
		message = ''

	row_count = len(master_sh.worksheet('Sheet1').get_all_records()) + 3

	master_sh.values_append('Sheet1!A'+str(row_count), {'valueInputOption': 'USER_ENTERED'}, {'values': [[contact_id,full_name,email,tags,phone,location_name,location_id,message]]})

app = Flask(__name__)
@app.route('/webhook', methods=['POST'])
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
