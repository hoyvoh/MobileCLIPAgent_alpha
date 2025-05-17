import requests

url = "http://127.0.0.1:8000/api/v1/agent/get_response/"
file_path = r"D:\LEARNING SPACE\GraduationProjectGogo\clip13k\cropped_dir\cropped_dir\107864817_1_cropped_0.jpg"

with open(file_path, "rb") as f:
    files = {
        "image": ("107864817_1_cropped_0.jpg", f, "image/jpeg"),
    }
    data = {
        "conversation_id": "123456",
        "user_id": "123456",
        "text": "hello",
    }
    response = requests.post(url, data=data, files=files)
    print(response.status_code)
    print(response.json())