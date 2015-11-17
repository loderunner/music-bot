from StringIO import StringIO
from datetime import datetime

from requests import get, post

import json
import redis
import sys

config = json.load(file('config.json'))

def send_message(content):
    res = post('https://api.flowdock.com/flows/%s/%s/messages' % (config['flowdock']['organization'], config['flowdock']['flow_id']),
         auth=(config['flowdock']['api_key'], ''),
         data={'event' : 'message',
               'content' : content
         }
        )
    if res.status_code >= 400:
        print 'Error %d %s' % (res.status_code, res.reason)
        print res.text

def send_comment(msg_id, content):
    res = post('https://api.flowdock.com/flows/%s/%s/messages/%d/comments' % (config['flowdock']['organization'], config['flowdock']['flow_id'], msg_id),
         auth=(config['flowdock']['api_key'], ''),
         data={'event' : 'comment',
               'content' : content
         }
        )
    if res.status_code >= 400:
        print 'Error %d %s' % (res.status_code, res.reason)
        print res.text

store = redis.StrictRedis(host=config['redis']['host'], port=config['redis']['port'], db=config['redis']['db'])

res = get('https://api.flowdock.com/user', auth=(config['flowdock']['api_key'], ''))
if res.status_code != 200:
    print 'Error: could not retrieve user id.'
    print 'HTTP Error:'
    print '\t%d %s' % (res.status_code, res.reason)
    print '\t' + res.text
    sys.exit(1)

user = res.json()
user_id = user['id']

stream = get('https://stream.flowdock.com/flows?filter=%s/%s' % (config['flowdock']['organization'], config['flowdock']['flow_id']),
             stream=True,
             auth=(config['flowdock']['api_key'], ''),
             headers={'Accept':'application/json'}
            )

msg_buf = StringIO()
for c in stream.iter_content():
    if c != '\r':
        msg_buf.write(c)
    elif c == '\n' and msg_buf.tell() == 0:
        pass
    else:
        this_msg = json.loads(msg_buf.getvalue())

        if (this_msg['event'] == 'message' or this_msg['event'] == 'comment' or this_msg['event'] == 'message-edit') and int(this_msg['user']) != user_id:
            content = this_msg['content']['updated_content'] if (this_msg['event'] == 'message-edit') else this_msg['content']
            if ('http://' in content
                or 'https://' in content
                or 'youtube.com' in content
                or 'soundcloud.com' in content):
                last_msg_id = store.get('lastmessage:%s' % this_msg['user'])

                if last_msg_id is not None:
                    res = get('https://api.flowdock.com/flows/%s/%s/messages/%s' % (config['flowdock']['organization'], config['flowdock']['flow_id'], last_msg_id),
                                auth=(config['flowdock']['api_key'], ''),
                            )
                    last_msg = res.json()

                    if res.status_code == 200:
                        this_date = datetime.fromtimestamp(this_msg['sent'] / 1000.0)
                        last_date = datetime.fromtimestamp(last_msg['sent'] / 1000.0)

                        if (this_date.year == last_date.year 
                            and this_date.month == last_date.month
                            and this_date.day == last_date.day):
                            msg_content = "You've already posted once today. Try to post only once a day.\nhttps://flowdock.com/app/%s/%s/messages/%d" % (config['flowdock']['organization'], config['flowdock']['flow_id'], last_msg['id'])
                            if this_msg['event'] == 'message':
                                msg_id = this_msg['id']
                            elif this_msg['event'] == 'comment':
                                for tag in this_msg['tags']:
                                    if tag.startswith('influx:'):
                                        msg_id = int(tag[len('influx:'):])
                                        break
                            if msg_id is not None:
                                send_comment(msg_id, msg_content)
                            else:
                                send_message(msg_content)

                store.set('lastmessage:%s' % this_msg['user'], this_msg['id'])
        msg_buf.seek(0)
        msg_buf.truncate()

if stream.status_code >= 400:
    print 'Error: could not get flow stream.'
    print 'HTTP Error:'
    print '\t%d %s' % (stream.status_code, stream.reason)
    print '\t' + stream.text
    sys.exit(1)
