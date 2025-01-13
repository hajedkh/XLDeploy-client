#!/usr/bin/env python
import requests
from requests.auth import HTTPBasicAuth
import xmltodict
import re 
import os
from dataclasses import dataclass
import csv
import difflib  
from typing import List



@dataclass
class DeployedApplication:
    ref: str
    environment: str
    version: str

    def __str__(self):
        print(f"{self.ref} ({self.version}")


class XLDeployClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.basic_auth = HTTPBasicAuth(username, password)

    def environment_exists(self, env) -> bool:
        resp = requests.get(f"{self.base_url}/deployit/repository/exists/{env}", verify=False, auth=self.basic_auth)
        if resp.status_code == 200:
            if resp.text == "<boolean>true</boolean>":
                return True
            else:
                # print(f"Environment {env} not found !")
                return False
        else:
                # print(f"Environment not found : status ={resp.status_code} ({resp.text})")
            return False

    def get_deployed_applications(self, env):
        resp = requests.get(
            f"{self.base_url}/deployit/environment/{env}/deployed-applications",
            verify=False, auth=self.basic_auth)
        lst = []
        if resp.status_code == 200:
            print("Response: " + resp.text)
            data = resp.json()
            for item in data:
                deployed_app = self.get_deployed_app_data(item["ref"].replace("\\", ""))
                lst.append(deployed_app)
        else:
            raise Exception(f"Error : {resp.status_code}, {resp.text}")
        return lst

    def read_configuration_item(self, type: str, ref):
        resp = requests.get(f"{self.base_url}/deployit/repository/ci/{ref}", verify=False, auth=self.basic_auth)
        if resp.status_code == 200:
            data = xmltodict.parse(resp.content)
            if type in data:
                return data[type]
            else:
                raise Exception(f"Wrong Data type for {ref}: expected= '{type}', actual='{data.keys()[0]}'")
        else:
            raise Exception(
                f"Error Querying XL Deploy for Configuration Item '{ref}' :Status =  {resp.status_code}, Text = {resp.text}")

    def get_deployed_app_data(self, ref):
        data = self.read_configuration_item("udm.DeployedApplication", ref)
        version = None
        environment = None
        if "version" in data and "@ref" in data["version"]:
            version = data["version"]["@ref"]
        if "environment" in data and "@ref" in data["environment"]:
            environment = data["environment"]["@ref"]
        return DeployedApplication(ref=ref, version=version, environment=environment)

    def search_configuration_items(self, ancestor, type: str, namePattern: str = None, pageSize=1000) -> list[
        str]:
        params = {}
        params["ancestor"] = ancestor
        params["type"] = type
        params["resultsPerPage"] = pageSize
        if namePattern:
            params["namePattern"] = namePattern
        resp = requests.get(f"{self.base_url}/deployit/repository/v2/query", params=params, verify=False,
                            auth=self.basic_auth)
        if resp.status_code == 200:
            result = []
            data = xmltodict.parse(resp.content)
            print(data)
            if "list" in data and data["list"] is not None and "ci" in data["list"]:
                if type(data["list"]["ci"]) == list:
                    for item in data["list"]["ci"]:
                        if "@ref" in item:
                            result.append(item["@ref"])
                else:
                    result.append(data["list"]["ci"]["@ref"])
            return result
        else:
            raise Exception(f"Error Searching CI : Status =  {resp.status_code}, Text = {resp.text}")

    def findEnvironment(self, ancestor, namePattern) -> list[str]:
        pageSize = 1000
        resp = requests.get(
            f"{self.base_url}/deployit/repository/v2/query?ancestor={ancestor}&type=udm.Environment&namePattern={namePattern}&resultsPerPage={pageSize}",
            verify=False, auth=self.basic_auth)
        if resp.status_code == 200:
            result = []
            data = xmltodict.parse(resp.content)
            # print(data)
            if "list" in data and data["list"] is not None and "ci" in data["list"]:
                if type(data["list"]["ci"]) == list:
                    for item in data["list"]["ci"]:
                        if "@ref" in item:
                            result.append(item["@ref"])
                else:
                    result.append(data["list"]["ci"]["@ref"])
            return result
        else:
            print(f"Error : {resp.status_code}, {resp.text}")

    def findAllEnvironment(self, ancestor) -> list[str]:
        # return self.search_configuration_items(ancestor=ancestor,type="udm.Environment")
        pageSize = 1000
        resp = requests.get(
            f"{self.base_url}/deployit/repository/v2/query?ancestor={ancestor}&type=udm.Environment&resultsPerPage={pageSize}",
            verify=False, auth=self.basic_auth)
        if resp.status_code == 200:
            result = []
            data = xmltodict.parse(resp.content)
            print(data)
            if "list" in data and data["list"] is not None and "ci" in data["list"]:
                if type(data["list"]["ci"]) == list:
                    for item in data["list"]["ci"]:
                        if "@ref" in item:
                            result.append(item["@ref"])
                else:
                    result.append(data["list"]["ci"]["@ref"])
            return result
        else:
            raise Exception(f"Error : {resp.status_code}, {resp.text}")
        
    def match_deployed_apps(self, old_env_name, new_env_name) -> str:

        old_envs = self.findAllEnvironment(old_env_name)
        new_envs = self.findAllEnvironment(new_env_name)

        old_apps = []
        new_apps = []

        for old_env in old_envs:
            print("searching for apps in ", old_env)
            try:
                apps = self.get_deployed_applications(old_env)
                filtered_apps = [app for app in apps if "secrets" not in app.ref.lower()]
                old_apps.extend(filtered_apps)  
                print(f"applications in  {old_env}: {len(apps)}")
            except Exception as e:
                print(f"error getting addps from {old_env}: {e}")

        for new_env in new_envs:
            try:
                apps = self.get_deployed_applications(new_env)
                filtered_apps = [app for app in apps if ("secrets" not in app.ref.lower() or "secrets" not in app.environment.lower()) ]
                new_apps.extend(filtered_apps)  
                print(f"applications in  {new_env}: {len(apps)}")
            except Exception as e:
                print(f"error getting appps from  {new_env}: {e}")

        csv_output = [["Application Name", "Old Environment (Production)","Old Version", "New ENvironment (PROD)"]]

        
        for old_app in old_apps:
            old_app_name = old_app.ref.split("/")[-1]  
            new_app_match = self.find_similar_app(old_app_name, new_apps)
            

            if new_app_match:
                similarr_env = self.find_similar_environment(old_app.environment, [app.environment for app in new_apps])
                csv_output.append([
                    old_app_name,
                    old_app.environment,
                    old_app.version,
                    (similarr_env if similarr_env else new_app_match.environment).replace("/STG/","/PROD/").replace("-stg",""),
                    #new_app_match.version 
                ])
            else:
                csv_output.append([old_app_name, old_app.environment, "Not Found"])

        csv_string = self.convert_to_csv(csv_output)
        return csv_string

    def find_similar_environment(self, old_env_name: str, new_envs: List[str]) -> str:
        closest_match = difflib.get_close_matches(old_env_name, new_envs, n=1, cutoff=0.8)
        return closest_match[0] if closest_match else None

    def find_similar_app(self, old_app_name: str, new_apps: List[DeployedApplication]) -> DeployedApplication:

        new_app_names = [app.ref.split("/")[-1] for app in new_apps]  
        closest_match = difflib.get_close_matches(old_app_name, new_app_names, n=1, cutoff=0.8)

        if closest_match:
            matched_app_name = closest_match[0]
            for new_app in new_apps:
                if new_app.ref.split("/")[-1] == matched_app_name:
                    return new_app
        return None  

    def convert_to_csv(self, data: List[List[str]]) -> str:
        output = []
        for row in data:
            output.append(",".join(row))
        return "\n".join(output)
    

    
    def deploy_application(self, app_ref: str,  target_env: str ) -> None:
        print("*************************STARTING THE DEPLOYMENT PROCESS***************************")
        print("Preparing deployment XML...")
        prepare_deploy_url = f"{self.base_url}/deployit/deployment/prepare/initial"
        params = {
            "version": app_ref,
            "environment": target_env
        }

        headers = {'Content-Type': 'application/json'}

        response = requests.get(prepare_deploy_url, headers=headers,params=params, verify=False, auth=self.basic_auth)
        deployment= None
        generated_deployment = None
        task_id= None

        if response.status_code == 200:
            deployment = response.text
            print(f"successfully generate deployment for  {app_ref} to {target_env} : {response.text}")
        else:
            print(f"failed to genertate deplyment  {app_ref}: {response.status_code} - {response.text}")

        if deployment: 
            print("Generating deployeds elements....")     
  
            deploy_url = f"{self.base_url}/deployit/deployment/generate/selected"
            parsed_depp = xmltodict.parse(deployment)
            deployables = parsed_depp['deployment']['deployables']['ci']
            deployable_refs=[]

            for deployable in deployables:
                 deployable_refs.append(deployable['@ref'])
           
            query_params = {
                "deployables": deployable_refs
            }

            headers = {
                "Content-Type": "application/xml",
                "Accept": "application/xml"
            }

            response = requests.post(deploy_url, headers=headers, data=deployment,params=query_params, verify=False, auth=self.basic_auth)    
            
            if response.status_code == 200:
                generated_deployment= response.text
                
                print(f"successfully generated deployeds for  {app_ref} to {target_env}.")
            else:
                print(f"failed to generate deployeds {app_ref}: {response.status_code} - {response.text}")
        else:
            print("Deployment does not exist ! Check initial step.")

        if generated_deployment: 
            print("Creating deployment task....")     
  
            deploy_url = f"{self.base_url}/deployit/deployment"

            headers = {
                "Content-Type": "application/xml",
                "Accept": "application/xml"
            }

            response = requests.post(deploy_url, headers=headers, data=generated_deployment, verify=False, auth=self.basic_auth)
            task_id=None

            if response.status_code == 200:
                task_id=response.text
                print(f"successfully created task for {app_ref} to {target_env}.")
            else:
                print(f"failed to deploy {app_ref}: {response.status_code} - {response.text}")
        else:
            print("Failed ton add selected deployeds elements !")


        
        if task_id:
            print("Staring deployment task....")   
            do_deploy_url = f"{self.base_url}/deployit/task/{task_id}/start"

            response_do_deploy = requests.post(do_deploy_url, verify=False, auth=self.basic_auth)

            if response_do_deploy.status_code == 204:
                print(response_do_deploy.text)
                print(f"successfully deployed app : {app_ref} in  {target_env}")
            else:
                print(f"failed to deploy  {response_do_deploy.status_code} - {response_do_deploy.text}")
        else:
            print("Failed To generate task for deployment check initial syteps")



    def update_deployed_application(self, app_ref: str, target_env: str) -> None:
        print("*************************STARTING THE Update PROCESS***************************")
        print("Preparing updated application deployment...")
        prepare_deploy_url = f"{self.base_url}/deployit/deployment/prepare/update"
        params = {
            "version": app_ref,
            "deployedApplication": f"{target_env}/{app_ref.split("/")[-2]}"
        }

        headers = {'Content-Type': 'application/json'}

        response = requests.get(prepare_deploy_url, headers=headers,params=params, verify=False, auth=self.basic_auth)
        deployment= None

        if response.status_code == 200:
            deployment = response.text
            print(f"successfully generate deployment for  {app_ref}  {response.text}")
        else:
            print(f"failed to genertate deplyment  {app_ref}: {response.status_code} - {response.text}")

        if deployment: 
            print("Creating deployment task....")     
  
            deploy_url = f"{self.base_url}/deployit/deployment"

            headers = {
                "Content-Type": "application/xml",
                "Accept": "application/xml"
            }

            response = requests.post(deploy_url, headers=headers, data=deployment, verify=False, auth=self.basic_auth)
            task_id= None

            if response.status_code == 200:
                task_id=response.text
                print(f"successfully created task for {app_ref} ")
            else:
                print(f"failed to deploy {app_ref}: {response.status_code} - {response.text}")
        else:
            print("Deployment does not exist ! Please verify your arguments (Application version , Environment)")
 

        if task_id:
            print("Staring deployment task....")   
            do_deploy_url = f"{self.base_url}/deployit/task/{task_id}/start"

            response_do_deploy = requests.post(do_deploy_url, verify=False, auth=self.base_url)

            if response_do_deploy.status_code == 204:
                print(response_do_deploy.text)
                print(f"successfully deployed")
            else:
                print(f"failed to deploy  {response_do_deploy.status_code} - {response_do_deploy.text}")
        else:
            print("Failed To generate task for deployment check initial syteps")






#prod_env = "Environments/Production"
#stg_env = "Environments/STG"
#csvOutput= cli.match_deployed_apps(prod_env, stg_env)

#print("writing in file ...")
#with open('matchEnv.csv', 'w', newline='') as file:
#    file.write(csvOutput)

#cli.update_deployed_application("Applications/service/outbound-media-service/sms-service/sms-service/1.2.5","Environments/TST/service/outbound-media-service/sms-service/sms-service-tst")



#
# for item in envs:
#     env_path = item.split("/")
#     app_name = re.sub("-tst$", "", env_path[-1])
#     found = cli.findEnvironment("Environments/Testing", f"{app_name}-testing")
#     if len(found) == 1:
#         print(f"App {app_name} : {found[0]} => {item}")
#     elif len(found) > 1:
#         print(f'Several environments found for app {app_name}: {found}')
#     else:
#         print(f"App {app_name} : Old Env path not found")
#
