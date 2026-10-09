import json, os
from dataclasses import dataclass, asdict

class CameraProfileStore:
    def __init__(self,path='config/cameras.json'):
        self.path=path
        os.makedirs(os.path.dirname(path),exist_ok=True)
        if not os.path.exists(path):
            with open(path,'w',encoding='utf8') as f: json.dump([],f)
    def list_enabled(self):
        with open(self.path,encoding='utf8') as f:
            return [x for x in json.load(f) if x.get('enabled',True)]
    def save(self,profile):
        with open(self.path,encoding='utf8') as f: data=json.load(f)
        data=[x for x in data if x.get('id')!=profile.get('id')]
        data.append(profile)
        with open(self.path,'w',encoding='utf8') as f: json.dump(data,f,indent=2)
