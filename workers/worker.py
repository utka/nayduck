import os
import socket
import sys
import subprocess
import psutil
import shutil
from pathlib import Path, PurePath
import time
from db import DB
from rc import bash, run
from multiprocessing import Process
import json
from azure.storage.blob import BlobServiceClient, ContentSettings
from os.path import expanduser

DEFAULT_TIMEOUT = 180
NUMS = 1
FAIL_PATTERNS = ['stack backtrace:']
INTERESTING_PATTERNS = ["LONG DELAY"]
AZURE = os.getenv('AZURE_STORAGE_CONNECTION_STRING')


def enough_space(filename="/datadrive"):
    try:
        df = subprocess.Popen(["df", filename], stdout=subprocess.PIPE, universal_newlines=True)
        output = df.communicate()[0]
        pr = output.split()[11]
        n_pr = int(str(pr)[:-1])
        if n_pr >= 65:
            return False
        return True
    except:
        return False


def prettify_size(size):
    if size < 1024: return size
    size //= 1024
    if size < 1024: return "%sK" % size
    size //= 1024
    if size < 1024: return "%sM" % size
    size //= 1024
    return "%sG" % size


def get_sequential_test_cmd(test):
    try:
        if test[0] == 'pytest' or test[0] == 'mocknet':
            return ["python", "tests/" + test[1]] + test[2:]
        elif test[0] == 'expensive':
            return ["cargo", "test", "--target-dir", "target_expensive", "-j2", "--color=always", "--package", test[1], "--test", test[2], test[3], 
                    "--all-features", "--", "--exact", "--nocapture"]
        elif test[0] == 'lib':
            return ["cargo", "test", "--target-dir", "target_expensive", "-j2", "--color=always", "--package", test[1], "--lib", test[2],
                    "--all-features", "--", "--exact", "--nocapture"]
        else:
            assert False, test
    except:
        print(test)
        raise


def install_new_packages(thread_n):
    try:
        print("Install new packages")
        f = open(f'''{thread_n}/pytest/requirements.txt''', 'r')
        required = {l.strip().lower() for l in f.readlines()}
        p = bash(f'''pip3 freeze''')
        rr = p.stdout.split('\n')
        installed = {k.split('==')[0].lower() for k in rr if k}
        missing = required - installed
        print(missing)
        if missing:
            python = sys.executable
            subprocess.check_call([python, '-m', 'pip', 'install', *missing], stdout=subprocess.DEVNULL)
    except Exception as e:
        print(e)

def run_test(thread_n, dir_name, test, remote=False):
    owd = os.getcwd()
    outcome = "FAILED"
    try:
        if test[0] == 'pytest' or test[0] == 'mocknet':
            os.chdir(os.path.join(str(thread_n), 'pytest'))
        else:
            os.chdir(str(thread_n))

        timeout = DEFAULT_TIMEOUT

        if len(test) > 1 and test[1].startswith('--timeout='):
            timeout = int(test[1][10:])
            test = [test[0]] + test[2:]

        if remote:
            timeout += 60 * 15

        cmd = get_sequential_test_cmd(test)

        if test[0] == 'pytest':
            node_dirs = subprocess.check_output("find ~/.near/test* -maxdepth 0 || true", shell=True).decode('utf-8').strip().split('\n')
            for node_dir in node_dirs:
                if node_dir:
                    shutil.rmtree(node_dir)
            subprocess.check_output('mkdir -p ~/.near', shell=True)

        print("[RUNNING] %s %s" % (' '.join(test), ' '.join(cmd)))

        stdout = open(os.path.join(dir_name, 'stdout'), 'w')
        stderr = open(os.path.join(dir_name, 'stderr'), 'w')

        env = os.environ.copy()
        env["RUST_BACKTRACE"] = "1"

        handle = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, env=env)
        try:
            ret = handle.wait(timeout)
            if ret == 0:
                ignored = False
                if test[0] == 'expensive' or test[0] == 'lib':
                    with open(os.path.join(dir_name, 'stdout')) as f:
                        lines = f.readlines()
                        while len(lines) and lines[-1].strip() == '':
                            lines.pop()
                        if len(lines) == 0:
                            ignored = True
                        else:
                            if '0 passed' in lines[-1]:
                                ignored = True
                outcome = 'PASSED' if not ignored else 'IGNORED'
                if test[0] == 'expensive' or test[0] == 'lib':
                    with open(os.path.join(dir_name, 'stderr')) as f:
                        lines = f.readlines()
                        for line in lines:
                            if line.strip() in FAIL_PATTERNS:
                                outcome = 'FAILED'
                                break
            elif ret == 13:
                return 'POSTPONE'
            else:
                outcome = 'FAILED'
                with open(os.path.join(dir_name, 'stdout')) as f:
                    lines = f.readlines()
                    while len(lines) and lines[-1].strip() == '':
                        lines.pop()
                    if len(lines) == 0:
                        outcome = 'FAILED'
                    else:
                        if '1 passed; 0 failed;' in lines[-1]:
                            outcome = 'PASSED'
        except subprocess.TimeoutExpired as e:
            stdout.flush()
            stderr.flush()
            sys.stdout.flush()
            sys.stderr.flush()
            outcome = 'TIMEOUT'
            print("Sending SIGINT to %s" % handle.pid)
            for child in psutil.Process(handle.pid).children(recursive=True):
                child.terminate()
            handle.terminate()
            handle.communicate()

        if test[0] == 'pytest':
            node_dirs = subprocess.check_output("find ~/.near/test* -maxdepth 0 || true", shell=True).decode('utf-8').strip().split('\n')
            for node_dir in node_dirs:
                if node_dir: # if empty, node_dirs will be always ['']
                    shutil.copytree(node_dir, os.path.join(dir_name, os.path.basename(node_dir)))

        print("[%7s] %s" % (outcome, ' '.join(test)))
        sys.stdout.flush()
    except Exception as ee:
        print(ee)
    os.chdir(owd)
    return outcome

def save_logs(server, test_id, dir_name):
    blob_size = 1024
    blob_service_client = BlobServiceClient.from_connection_string(AZURE)
    cnt_settings = ContentSettings(content_type="text/plain")
    files = []
    for filename in os.listdir(dir_name):
        if os.path.isdir(os.path.join(dir_name, filename)):
            fl_name = filename.split('_')[0]
            if os.path.exists(os.path.join(dir_name, filename, "remote.log")):
                files.append((fl_name + "_remote", os.path.join(dir_name, filename, "remote.log")))
            if os.path.exists(os.path.join(dir_name, filename, "companion.log")):
                files.append((fl_name + "_companion", os.path.join(dir_name, filename, "companion.log")))
            if os.path.exists(os.path.join(dir_name, filename, "stderr")):
                files.append((fl_name, os.path.join(dir_name, filename, "stderr")))
        elif filename in ["stderr", "stdout", "build_err", "build_out"]:
            files.append((filename, os.path.join(dir_name, filename)))
    home = expanduser("~")
    if os.path.isdir(os.path.join(home, ".rainbow", "logs")):
        for folder in os.listdir(os.path.join(home, ".rainbow", "logs")):
            for filename in os.listdir(os.path.join(home, ".rainbow", "logs", folder)):
                if "err" in filename:
                    files.append((f"{folder}_err", os.path.join(home, ".rainbow", "logs", folder, filename)))
                if "out" in filename:
                    files.append((f"{folder}_out", os.path.join(home, ".rainbow", "logs", folder, filename)))

    for fl_name, fl in files:
        stack_trace = False
        data = ""
        file_size = prettify_size(os.path.getsize(fl))
        res = bash(f'''grep "stack backtrace:" {fl}''')
        if res.returncode == 0:
            stack_trace = True
        found_patterns = []
        for pattern in INTERESTING_PATTERNS:
            res = bash(f'''grep "{pattern}" {fl}''')
            if res.returncode == 0:
                found_patterns.append(pattern)
        blob_name = str(test_id) + "_" + fl_name
        s3 = ""
        with open(fl, 'rb') as f:
            f.seek(0)
            beginning = f.read(blob_size * 5 * 2).decode()
            if len(beginning) < blob_size * 5 * 2:
                data = beginning
            else:
                data = beginning[0:blob_size * 5]
                data += '\n...\n'
                f.seek(-blob_size * 5, 2)
                data += f.read().decode()
        blob_client = blob_service_client.get_blob_client(container="logs", blob=blob_name)    
        with open(fl, 'rb') as f:
            blob_client.upload_blob(f, content_settings=cnt_settings)
            s3 = blob_client.url
        print(s3) 
        server.save_short_logs(test_id, fl_name, file_size, data, s3, stack_trace, ",".join(found_patterns))
            

def build_fail_cleanup(bld, thread_n):
    bash(f'''
            rm -rf {thread_n}
    ''')
    return bld.returncode

def build(sha, thread_n, outdir, build_before, hostname, remote, release):
    already_exists = bash(f'''
                    cd {thread_n}
                    git rev-parse HEAD
    ''')
    print(already_exists)
    sys.stdout.flush()
    if already_exists.returncode == 0 and already_exists.stdout.strip() == sha and build_before:
        print('Woohoo! Skipping the build.')
        sys.stdout.flush()
        return 0
    if not enough_space():
        print("Not enough space.")
        bld = bash(f'''rm -rf {thread_n}''')
    with open(str(outdir) + '/build_out', 'w') as fl_o:
        with open(str(outdir) + '/build_err', 'w') as fl_e:
            kwargs = {"stdout": fl_o, "stderr": fl_e}
            bash('''docker build . -f pytest-runtime.Dockerfile -t pytest-runtime''')
            print("Checkout")
            bld = bash(f'''
                cd {thread_n}
                git fetch
                git checkout {sha}
            ''' , **kwargs, login=True)
            print(bld)
            if bld.returncode != 0:
                print("Clone")
                bld = bash(f'''
                    rm -rf {thread_n}
                    git clone https://github.com/nearprotocol/nearcore {thread_n}
                    cd {thread_n}
                    git checkout {sha}
                ''' , **kwargs, login=True)
                print(bld)
                if bld.returncode != 0:
                    return build_fail_cleanup(bld, thread_n)
            if "mocknet" in hostname:
                print("Skipping the build for mocknet tests")
                return 0
            if remote:
                print("Build for remote.")
                bld = bash(f'''
                    cd {thread_n}
                    cargo build -j2 -p neard --features adversarial
                ''' , **kwargs, login=True)
                if bld.returncode != 0:
                    return build_fail_cleanup(bld, thread_n)
                return 0
            print("Build")
            bld = bash(f'''
                cd {thread_n}
                cargo build -j2 -p neard --features adversarial {release}
                cargo build -j2 -p genesis-populate {release}
                cargo build -j2 -p restaked {release}
            ''' , **kwargs, login=True)
            print(bld)
            if bld.returncode != 0:
                return build_fail_cleanup(bld, thread_n)
            bld = run(f'''cd {thread_n} && cargo test -j2 --workspace --no-run --all-features --target-dir target_expensive {release}''', **kwargs)
            if bld.returncode != 0:
                return build_fail_cleanup(bld, thread_n)
            bld = run(f'''cd {thread_n} && cargo build -j2 -p neard --target-dir normal_target {release}''', **kwargs)
            if bld.returncode != 0:
                return build_fail_cleanup(bld, thread_n)
            return 0    


def keep_pulling(thread_n):
    hostname = socket.gethostname()
    build_before = False
    while True:
        try:
            server = DB()
            time.sleep(5)
            test = server.get_pending_test(hostname)
            if not test:
                continue
            print(test)
            shutil.rmtree(os.path.abspath('output/'), ignore_errors=True)
            outdir = os.path.abspath('output/' + str(test['run_id']) + '/' + str(test['test_id']))
            Path(outdir).mkdir(parents=True, exist_ok=True)
            remote = False
            config_override = {}
            if "NEAR_PYTEST_CONFIG" in os.environ:
                del os.environ["NEAR_PYTEST_CONFIG"]
            if '--remote' in test['name']: 
                remote = True
                config_override['local'] = False
                config_override['preexist'] = True
                os.environ["NEAR_PYTEST_CONFIG"] = "/datadrive/nayduck/.remote"
                test['name'] = test['name'].replace(' --remote', '')
            release = ""
            if '--release' in test['name']:
                release = "--release"
                config_override['release'] = True
                os.environ["NEAR_PYTEST_CONFIG"] = "/datadrive/nayduck/.remote"
                test['name'] = test['name'].replace(' --release', '')
            if "NEAR_PYTEST_CONFIG" in os.environ:
                with open("/datadrive/nayduck/.remote", "w") as f:
                    json.dump(config_override, f)

            code = build(test['sha'], thread_n, outdir, build_before, hostname, remote, release)
            server = DB()
            if code != 0:
                server.update_test_status('BUILD FAILED', test['test_id'])
                save_logs(server, test['test_id'], outdir)
                continue
            build_before = True
            install_new_packages(thread_n)
            server.create_timestamp_for_test_started(test['test_id'])
            code = run_test(thread_n, outdir, test['name'].strip().split(' '), remote)
            server = DB()
            if code == 'POSTPONE':
                server.remark_test_pending(test['test_id'])
                continue
            server.update_test_status(code, test['test_id'])
            save_logs(server, test['test_id'], outdir)
        except Exception as e:
            print(e)

if __name__ == "__main__":
    server = DB()
    server.handle_restart(socket.gethostname())
    ps = []
    for i in range(NUMS):
        p = Process(target=keep_pulling, args=(i,))
        p.start()
        ps.append(p)

    for p in ps:
        p.join()
        
