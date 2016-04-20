from __future__ import print_function

import json
import uuid

import requests
import boto3
from botocore.exceptions import ClientError

print('Loading function')

PAGE_TOKEN = '<INSERT YOUR FACEBOOK PAGE TOKEN HERE>'

FB_SEND_MSG_ENDPOINT = 'https://graph.facebook.com/v2.6/me/messages'

SQS_CLIENT = boto3.client('sqs')
DYNAMODB_CLIENT = boto3.client('dynamodb')


POSTBACK_NEXT_USER = 'NEXT_USER'
POSTBACK_CLOSE_CHAT = 'CLOSE_CHAT'

# Waitlist
SQS_QUEUE_WAITLIST_URL = '<INSERT SQS QUEUE URL HERE>'
{
    '<id>': '<userId1>'
}

# Users:
DYNAMODB_TABLENAME_USERS = 'fbUsers'
[
    {
        'user_id': { 'N': 'user_id' },
        'current_conversation_id': { 'S': 'conversation_id' },
    },
]

# Ongoing conversations:
DYNAMODB_TABLENAME_CONVERSATIONS = 'fbConversations'
[
    {
        'conversation_id': { 'S': 'sqs_message_id' },
        'user_id_1': { 'N': 'user_id' },
        'user_id_2': { 'N': 'user_id' },
        'started': { 'N': 'timestamp' },
        'stopped': { 'N': 'timestamp' },
    },
]

# Messages
DYNAMODB_TABLENAME_MESSAGES = 'fbMessages'
[
    {
        'mid': { 'N': 'mid' },
        'sender_id': { 'N': 'sender_id' },
        'recipient_id': { 'N': 'recipient_id' },
        'timestamp': { 'N': 'timestamp' },
        'seq_num': { 'N': 'seq_num' },
        'text': { 'S': 'text' },
        'conversation_id': { 'S': 'conversation_id' },
    },
]

def lambda_handler(event, context):
    body = event.get('body')
    if body is None:
        return 'Invalid body'

    for entry in body.get('entry', []):
        page_id = entry.get('id')
        entry_time = entry.get('time')

        for event in entry.get('messaging', []):
            print('event', event)
            sender_id = event['sender']['id']
            recipient_id = event['recipient']['id']
            timestamp = event.get('timestamp')

            for handler, prop_name in WEBHOOK_HANDLERS:
                prop = event.get(prop_name)
                if prop is not None:
                    handler(sender_id, recipient_id, timestamp, prop)
                    return


##
## Handle responses
##

def get_conversation_id(user_id):
    response = DYNAMODB_CLIENT.get_item(
        TableName=DYNAMODB_TABLENAME_USERS,
        Key={ 'user_id': { 'N': str(user_id) } },
        ProjectionExpression='current_conversation_id',
        ConsistentRead=True,
    )
    try:
        return response['Item']['current_conversation_id']['S']
    except KeyError:
        return None

def get_other_user_id(user_id, conversation_id):
    response = DYNAMODB_CLIENT.get_item(
        TableName=DYNAMODB_TABLENAME_CONVERSATIONS,
        Key={ 'conversation_id': { 'S': conversation_id } },
        ProjectionExpression='user_id_1,user_id_2',
        ConsistentRead=True,
    )

    user_id_1 = response['Item']['user_id_1']['N']
    user_id_2 = response['Item']['user_id_2']['N']

    sender_id_str = str(user_id)
    if sender_id_str == user_id_1:
        return user_id_2
    elif sender_id_str == user_id_2:
        return user_id_1
    else:
        print('Sender (%s) is not a member of the conversation (%s) between (%s) and (%s)' % (sender_id_str, conversation_id, user_id_1, user_id_2))
        return None



def handle_message(sender_id, recipient_id, timestamp, message):
    message_id = message.get('mid')
    seq_num = message.get('seq')
    text = message.get('text')

    # Check if the user is currently in a conversation
    conversation_id = get_conversation_id(sender_id)

    # If we have already processed the message, skip further processing. Otherwise, save it.
    try:
        item = {
            'mid': { 'S': message_id },
            'sender_id': { 'N': str(sender_id) },
            'recipient_id': { 'N': str(recipient_id) },
            'timestamp': { 'N': str(timestamp) },
            'seq_num': { 'N': str(seq_num) },
            'text': { 'S': text },
        }

        if conversation_id is not None:
            item['conversation_id'] = { 'S': conversation_id }

        DYNAMODB_CLIENT.put_item(
            TableName=DYNAMODB_TABLENAME_MESSAGES,
            Item=item,
            ConditionExpression='attribute_not_exists(mid)',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == "ConditionalCheckFailedException":
            # The message was already processed, stop processing
            print('mid %s was already processed, skipping' % message_id)
            return
        else:
            # We weren't expecting this error, raise
            raise


    if conversation_id is None:
        # If the user is not in a conversation, send the get started message
        send_get_started_message(sender_id)
    else:
        # If the user is in a conversation, look up that conversation and send a message to the other person
        other_user_id = get_other_user_id(sender_id, conversation_id)

        send_chat_message(other_user_id, text)


def handle_postback(sender_id, recipient_id, timestamp, postback):
    if postback.get('payload') == POSTBACK_NEXT_USER:
        # If the user is currently in a conversation, remove the conversation_id from both user objects
        conversation_id = get_conversation_id(sender_id)
        if conversation_id is not None:
            other_user_id = get_other_user_id(sender_id, conversation_id)

            for user_id in (str(sender_id), other_user_id):
                DYNAMODB_CLIENT.put_item(
                    TableName=DYNAMODB_TABLENAME_USERS,
                    Item={
                        'user_id': { 'N': user_id },
                    },
                )
                send_text_message(user_id, 'You have been disconnected from this user')

        response = DYNAMODB_CLIENT.get_item(
            TableName=DYNAMODB_TABLENAME_USERS,
            Key={ 'user_id': { 'N': str(sender_id) } },
            ProjectionExpression='in_queue',
            ConsistentRead=True,
        )

        try:
            in_queue = response['Item']['in_queue']['BOOL']
        except KeyError:
            in_queue = False

        if in_queue:
            print ('User %s already in queue, skipping request' % str(sender_id))
            send_text_message(sender_id, 'Waiting for another user...')
            return

        # Get a user from the queue
        response = SQS_CLIENT.receive_message(
            QueueUrl=SQS_QUEUE_WAITLIST_URL,
            AttributeNames=[
                'SentTimestamp',
                'ApproximateReceiveCount',
            ],
            MessageAttributeNames=[
                'string',
            ],
            MaxNumberOfMessages=1,
            WaitTimeSeconds=3,
        )

        messages = response.get('Messages')

        if messages is None or len(messages) == 0:
            # Add this user to the queue
            response = SQS_CLIENT.send_message(
                QueueUrl=SQS_QUEUE_WAITLIST_URL,
                MessageBody=str(sender_id),
            )

            DYNAMODB_CLIENT.put_item(
                TableName=DYNAMODB_TABLENAME_USERS,
                Item={
                    'user_id': { 'N': str(sender_id) },
                    'in_queue': { 'BOOL': True },
                },
            )

            send_text_message(sender_id, 'Waiting for another user...')
        else:
            message = messages[0]

            message_id = message['MessageId']
            other_user_id = message['Body']
            receipt_handle = message['ReceiptHandle']

            if other_user_id == str(sender_id):
                print ('User %s pulled themselves from the queue, skipping' % other_user_id)
                send_text_message(sender_id, 'Waiting for another user...')
                return

            # WARNING: Bug if the new convo succeeds but the delete user from queue fails
            # Start new convo - Get user from SQS or add this user to SQS
            conversation_id = message_id
            try:
                DYNAMODB_CLIENT.put_item(
                    TableName=DYNAMODB_TABLENAME_CONVERSATIONS,
                    Item={
                        'conversation_id': { 'S': conversation_id },  # Hack - just use the SQS message ID as the conversation ID to ensure we don't process the same SQS message multiple times
                        'user_id_1': { 'N': str(sender_id) },
                        'user_id_2': { 'N': other_user_id },
                        'started': { 'N': str(timestamp) },
                    },
                    ConditionExpression='attribute_not_exists(conversation_id)',
                )
            except ClientError as e:
                if e.response['Error']['Code'] == "ConditionalCheckFailedException":
                    # The SQS message was already processed, continue
                    print('Tried to process the same SQS message twice: %s' % conversation_id)
                else:
                    # We weren't expecting this error, raise
                    raise

            # Add both users to the conversation and send them initial messages to let them know they are connected
            for user_id in (str(sender_id), other_user_id):
                DYNAMODB_CLIENT.put_item(
                    TableName=DYNAMODB_TABLENAME_USERS,
                    Item={
                        'user_id': { 'N': user_id },
                        'current_conversation_id': { 'S': conversation_id },
                    },
                )

                send_text_message(user_id, 'You are now chatting with someone - say hi!')


            # Delete the message from the queue
            response = SQS_CLIENT.delete_message(
                QueueUrl=SQS_QUEUE_WAITLIST_URL,
                ReceiptHandle=receipt_handle,
            )

def handle_auth(sender_id, recipient_id, timestamp, optin):
    pass


WEBHOOK_HANDLERS = (
    (handle_auth, 'optin'),
    (handle_postback, 'postback'),
    (handle_message, 'message'),
)


##
## Send messages
##


def send_text_message(recipient_id, text):
    send_message(recipient_id, {'text': text})

def send_chat_message(recipient_id, text):
    buttons = [
        {
            'type': 'postback',
            'title': 'New chat',
            'payload': POSTBACK_NEXT_USER,
        },
        {
            'type': 'postback',
            'title': 'End chat',
            'payload': POSTBACK_CLOSE_CHAT,
        },
    ]

    send_button_message(recipient_id, text, buttons)

def send_get_started_message(recipient_id):
    text = 'Get started - chat with a rando'
    buttons = [
        {
            'type': 'postback',
            'title': 'Chat with a stranger',
            'payload': POSTBACK_NEXT_USER,
        },
    ]

    send_button_message(recipient_id, text, buttons)

def send_button_message(recipient_id, text, buttons):
    message_data = {
        'attachment': {
            'type': 'template',
            'payload': {
                'template_type': 'button',
                'text': text,
                'buttons': buttons,
            }
        }
    }

    send_message(recipient_id, message_data)


def send_message(recipient_id, message_data):
    params = {
        'access_token': PAGE_TOKEN,
    }

    data = {
        'recipient': {
            'id': str(recipient_id)
        },
        'message': message_data,
    }

    print ('message_data', message_data)

    r = requests.post(FB_SEND_MSG_ENDPOINT, params=params, json=data)

    if r.status_code != requests.codes.ok:
        print(r, r.text)
