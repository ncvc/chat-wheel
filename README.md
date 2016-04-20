# chat-wheel
Bare-bones Chatroulette clone for the FB Messenger Bot Platform on AWS Lambda.

It basically waits for users to message it. Once they do, the bot will match users with each other to start a conversation. Users' messages are then forwarded to each other. Either user can end the conversation at any time and get matched with a new user.

Runs entirely on AWS services - Lambda, DynamoDB, SQS (overkill, but I wanted to check it out).

Definitely not production-ready

## Setup
1. Follow installation instructions
2. Provision AWS Resources as described below
3. Set up a Facebook Page and App as described [here](https://developers.facebook.com/docs/messenger-platform/quickstart)
4. Insert your Facebook Page Token and SQS Queue url into `lambda_function.py`
5. Deploy the lambda function

## Local Installation
1. Install and configure the [AWS CLI](http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html) with your account's login credentials
2. Create virtualenv, then `pip install -r requirements.txt`

## AWS Resources
- Lambda function
	- Make sure to give the lambda function a Role that enables it to `r/w` DynamoDB, `r/w` SQS, and `w` CloudWatch Logs (for debugging)
- SQS Queue (I called mine `fbWaitlist`)
- DynamoDB
	- Tables
		- Name: `fbConversations`, Primary Partition Key: `conversation_id (String)`
		- Name: `fbMessages`, Primary Partition Key: `mid (String)`
		- Name: `fbUsers`, Primary Partition Key: `user_id (Number)`

## Testing Locally
Run `python test_lambda.py`. Modify as appropriate. Hacky, but workable.
