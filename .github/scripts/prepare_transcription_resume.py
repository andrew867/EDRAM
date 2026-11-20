import datetime
import json
import os
import time
import urllib.request

repo=os.environ["GITHUB_REPOSITORY"]
token=os.environ["GITHUB_TOKEN"]
run_id=44833302073
base=f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"


def api(url,method="GET"):
    request=urllib.request.Request(url,method=method,headers={
        "Authorization":f"Bearer {token}","Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28","User-Agent":"EDRAM-transcription-resume"})
    with urllib.request.urlopen(request,timeout=30) as response:
        body=response.read()
    return json.loads(body) if body else None


def main():
    for _ in range(30):
        run=api(base)
        if run["status"]=="completed":
            break
        started=datetime.datetime.fromisoformat(run["run_started_at"].replace("Z","+00:00"))
        elapsed=(datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()
        jobs=api(base+"/jobs?per_page=100")["jobs"]
        recognizing=[j for j in jobs if j["name"].startswith("transcribe") and j["status"]=="in_progress"]
        print(json.dumps({"status":run["status"],"elapsed_seconds":round(elapsed),"recognizing":len(recognizing)}),flush=True)
        if elapsed>=1800 and recognizing:
            api(base+"/cancel",method="POST")
            print("Requested cancellation so always-run artifact steps can preserve per-clip checkpoints.",flush=True)
            for _ in range(30):
                time.sleep(5)
                run=api(base)
                if run["status"]=="completed":
                    break
            break
        time.sleep(10)
    run=api(base)
    resume=not (run["status"]=="completed" and run["conclusion"]=="success")
    with open(os.environ["GITHUB_OUTPUT"],"a") as output:
        output.write("resume="+str(resume).lower()+"\n")
    print(json.dumps({"resume":resume,"previous_status":run["status"],"previous_conclusion":run["conclusion"]}),flush=True)


if __name__=="__main__":
    main()
