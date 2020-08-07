from flask import Flask, session, flash, render_template, redirect, json, url_for, request, abort, make_response, jsonify, send_file
from rc import bash, ok
import os

from db import DB

app = Flask(__name__)

app.config['TEMPLATES_AUTO_RELOAD'] = True


@app.route('/request_a_run', methods=['POST', 'GET'])
def request_a_run():
    request_json = request.get_json(force=True) 
    if not request_json['branch'] or not request_json['sha']:
        resp = {'code': 1, 'response': 'Failure. Branch and/or git sha were not provided.'}
        return jsonify(resp)
    
    fetch = bash(f'''
            rm -rf nearcore
            git clone https://github.com/nearprotocol/nearcore
            cd nearcore
            git fetch 
            git checkout {request_json['sha']}
    ''')
    if fetch.returncode == 0:
        user = bash(f'''
            cd nearcore
            git log --format='%ae' {request_json['sha']}^!
        ''').stdout
        title = bash(f'''
            cd nearcore
            git log --format='%s' {request_json['sha']}^!
        ''').stdout
        tests = []
        for x in request_json['tests']:
                if len(x.strip()) and x[0] != '#':
                    spl = x.split(' ', 1)
                    if spl[0].isnumeric():
                        tests.extend([spl[1]] * int(spl[0]))
                    else:
                        tests.append(x)
        server = DB()
        run_id = server.scheduling_a_run(branch=request_json['branch'],
                                  sha=request_json['sha'],
                                  user=user.split('@')[0],
                                  title=title,
                                  tests=tests)
        resp = {'code': 0, 'response': 'Success. ' + os.getenv('NAYDUCK_UI') + '/run/' + str(run_id)}
    else:
        resp = {'code': 1, 'response': 'Failure. ' + str(fetch.stderr)}
    return jsonify(resp)


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
    