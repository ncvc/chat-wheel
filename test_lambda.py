import lambda_function

MSG = {
	"sender":{
		"id":"11111"
	},
	"recipient":{
		"id":"5555"
	},
	"timestamp":1457764197627,
	"message":{
		"mid":"mid.12345:54321",
		"seq":73,
		"text":"hello, world!"
	}
}

MSG = {
	u'timestamp': 1460870880139,
	u'postback': {
		u'payload': u'NEXT_USER'
	},
	u'recipient': {
		u'id': 12345
	},
	u'sender': {
		u'id': 12345
	}
}


EVENT = {
	'body': {
		"object":"page",
		"entry":[
			{
				"id": "page_id",
				"time":1457764198246,
				"messaging":[ MSG ],
			}
		]
	}
}
CONTEXT = None

if __name__ == '__main__':
	print('Response:', lambda_function.lambda_handler(EVENT, CONTEXT))
