import google.generativeai as genai

genai.configure(api_key='YOUR_API_KEY')
model = genai.GenerativeModel("gemini-1.5-pro")
myfile = genai.upload_file('path/to/video.mp4')
response = model.generate_content([myfile, "Describe this video"])
print(response.text)