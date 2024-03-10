import os
import base64
import re
import webview
import pyotp
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText



# Initialize Flask app
app = Flask(__name__)   # Create a Flask app
app.secret_key = 'uLKrvX,c*!gvkP7]~hRvo6H+:r"5PzD12"MMC#5s+[hO>PbByA=@{Q1=MampaB)'  # Set a secret key for the app



# Create window for webview
window = webview.create_window("QuadBudget AI", app)



# Initialize Flask-Login
login_manager = LoginManager()  # Create a LoginManager instance
login_manager.init_app(app) # Initialize the LoginManager instance



# Initialize Firestore
cred = credentials.Certificate('quadbudget-db.json')   # Use the service account key JSON file to initialize the app
firebase_admin.initialize_app(cred) # Initialize the app with the credentials
db = firestore.client() # Create an instance of the Firestore client



# Define the Generative AI model
genai.configure(api_key="AIzaSyB5b3yOq6uW3V32P5WeCEDuU-KSGP1hfbU")  # Set the API key for the Generative AI service
generation_config = {
  "temperature": 1,
  "top_p": 1,
  "top_k": 1,
  "max_output_tokens": 4096,
}   # Set the generation configuration for the Generative AI service
safety_settings = [
  {
    "category": "HARM_CATEGORY_HARASSMENT",
    "threshold": "BLOCK_ONLY_HIGH"
  },
  {
    "category": "HARM_CATEGORY_HATE_SPEECH",
    "threshold": "BLOCK_ONLY_HIGH"
  },
  {
    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "threshold": "BLOCK_ONLY_HIGH"
  },
  {
    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
    "threshold": "BLOCK_ONLY_HIGH"
  },
]   # Set the safety settings for the Generative AI service
model = genai.GenerativeModel(model_name="gemini-1.0-pro-001", generation_config=generation_config, safety_settings=safety_settings)    # Create an instance of the Generative AI model



# Define User class
class User(UserMixin):  # Create a User class that inherits from UserMixin
    def __init__(self, user_id):    # Define the __init__ method
        self.id = user_id   # Set the user_id attribute of the User instance to the user_id argument



# Flask-Login user loader
@login_manager.user_loader  # Use the user_loader decorator to register the user_loader callback
def load_user(user_id): # Define the load_user function
    return User(user_id)    # Return a User instance with the user_id argument as the user_id attribute



def add_record(user_id, bill_name, due_date, amount):   # Define the add_record function
    if datetime.strptime(due_date, '%Y-%m-%d') < datetime.now():    # If the due date has passed
        record_ref = db.collection('users').document(user_id).collection('records').document()  # Create a reference to the record document
        record_ref.set({
            'Date': due_date,
            'type': 'debit',  # Assuming bill reminder is a debit
            'amount': amount,      
            'reason': bill_name,
            'description': 'Automatically generated record for bill: ' + bill_name
        })  # Set the fields of the record document



def format_text_to_html(text):  # Define the format_text_to_html function
    formatted_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)   # Replace ** with <b> and </b>
    formatted_text = re.sub(r'^\* (.*?)$', r'<li>\1</li>', formatted_text, flags=re.MULTILINE)  # Replace * with <li> and </li>
    formatted_text = re.sub(r'^(\d+)\. (.*?)$', r'<li>\1. \2</li>', formatted_text, flags=re.MULTILINE) # Replace 1. with <li> and </li>
    formatted_text = re.sub(r'^<b>(.*?)</b>(.*?)<b>', r'<h2>\1</h2>\2<b>', formatted_text, flags=re.MULTILINE)  # Replace <b> and </b> with <h2> and </h2>
    formatted_text = re.sub(r'^(?![\s*<])(.*)$', r'<p>\1</p>', formatted_text, flags=re.MULTILINE)  # Replace text with <p> and </p>
    return formatted_text   # Return the formatted text



def send_email(username, email, password, totp_secret): # Define the send_email function
    SCOPES = ['https://www.googleapis.com/auth/gmail.send'] # Set the scopes for the Gmail API

    # Get Gmail service
    creds = None    # Initialize the creds variable to None
    if os.path.exists('token.json'):    # If the token.json file exists
        creds = Credentials.from_authorized_user_file('token.json')   # Get the credentials from the token.json file
    if not creds or not creds.valid:    # If the credentials are not valid
        if creds and creds.expired and creds.refresh_token:   # If the credentials are expired and a refresh token exists
            creds.refresh(Request())    # Refresh the credentials
        else:   # If the credentials are not expired or a refresh token does not exist
            flow = InstalledAppFlow.from_client_secrets_file(   # Create a flow from the client secrets file
                'quadbudget-mail.json', SCOPES)   # Use the SCOPES list
            creds = flow.run_local_server(port=0)   # Run the flow on a local server
        with open('token.json', 'w') as token:  # Open the token.json file in write mode
            token.write(creds.to_json())    # Write the credentials to the file

    service = build('gmail', 'v1', credentials=creds)   # Build the Gmail service

    # Construct email message
    message = MIMEMultipart()   # Create a MIMEMultipart instance
    message['to'] = email   # Set the to field of the message
    message['subject'] = "Registration Details"  # Set the subject of the message
    email_body = f"Here are your Details for the app 'QuadWealth AI', Keep Them Safely:\nUsername: {username}\nEmail: {email}\nPassword: {password}\nTOTP Secret: {totp_secret}\nUse the Above TOTP Secret With a Authenticator App. If this Secret Gets Lost, You'll loose your 'Account'"  # Set the email body
    message.attach(MIMEText(email_body, 'plain'))   # Attach the email body to the message
    
    raw_message = base64.urlsafe_b64encode(message.as_bytes())  # Encode the message using base64
    raw_message = raw_message.decode()  # Decode the message
    
    service.users().messages().send(userId='me', body={'raw': raw_message}).execute()   # Send the email



def totp_verify(otp, totp_secret):  # Define the totp_verify function
    totp = pyotp.TOTP(totp_secret)  # Create a TOTP object with the totp_secret
    return totp.verify(otp) # Verify the OTP against the secret



@app.route('/') # Define the route for the index page
def index():    # Define the index function
    return render_template('index.html')    # Render the index.html template



@app.route('/register', methods=['GET', 'POST'])    # Define the route for the register page
def register(): # Define the register function
    if request.method == 'POST':    # If the request method is POST
        username = request.form['username']   # Get the username from the form
        email = request.form['email']   # Get the email from the form
        password = request.form['password']     # Get the password from the form
        password_confirm = request.form['repeated_password']    # Get the repeated password from the form
        bank_balance = float(request.form['bank_balance'])  # Get the bank balance from the form
        pass64 = base64.b64encode(password.encode("utf-8")) # Encode the password using base64
        totp_secret = pyotp.random_base32()    # Generate a random base32 secret for TOTP
        
        # Check if passwords match
        if password == password_confirm:    # If the password and repeated password match
            if db.collection('users').document(username).get().exists:  # If a user document with the username already exists
                return 'Username already taken. Please choose another username.'    # Return a message indicating that the username is already taken
            
            # Create new user document
            user_ref = db.collection('users').document(username)    # Create a reference to the user document
            user_ref.set({
                'username': username,
                'email': email,
                'password': pass64,
                'bank_balance': bank_balance,
                'totp_secret': totp_secret
            })  # Set the fields of the user document

            send_email(username, email, password, totp_secret)  # Send an email to the user with their TOTP secret

            return redirect(url_for('index'))   # Redirect to the index page
        else:   # If the password and repeated password do not match
            return 'Passwords do not match. Please try again.'  # Return a message indicating that the passwords do not match
        
    return render_template('register.html')   # Render the register.html template



@app.route('/login', methods=['GET', 'POST'])   # Define the route for the login page
def login():    # Define the login function
    if request.method == 'POST':    # If the request method is POST
        username = request.form['username']  # Get the username from the form
        password = request.form['password'] # Get the password from the form
        pass64 = base64.b64encode(password.encode("utf-8")) # Encode the password using base64
        
        user_ref = db.collection('users').document(username)    # Create a reference to the user document
        user_doc = user_ref.get()   # Get the user document
        
        if not user_doc.exists or user_doc.to_dict()['password'] != pass64: # If the user document does not exist or the password is incorrect
            return 'Invalid username or password'   # Return a message indicating that the username or password is invalid
        
        totp_secret = user_doc.to_dict()['totp_secret']  # Get the totp_secret field from the user document
        if totp_verify(request.form['totp'], totp_secret):  # If the OTP is verified
            # Create a User instance and pass it to login_user
            user = User(user_id=username)  # Assuming User class expects user_id in its constructor
            login_user(user)    # Log the user in
            return redirect(url_for('dashboard'))   # Redirect to the dashboard page
        else:   # If the OTP is not verified
            return 'Invalid OTP'    # Return a message indicating that the OTP is invalid
        
    return render_template('login.html')    # Render the login.html template



@app.route('/forgot_password', methods=['GET', 'POST'])    # Define the route for the forgot password page
def forgot_password():  # Define the forgot_password function
    if request.method == 'POST':    # If the request method is POST
        username = request.form['username']  # Get the username from the form
        email = request.form['email']   # Get the email from the form
        new_password = request.form['new_password']   # Get the new password from the form

        user_ref = db.collection('users').document(username)    # Create a reference to the user document
        user_doc = user_ref.get()   # Get the user document
        totp_secret = user_doc.to_dict()['totp_secret']  # Get the totp_secret field from the user document
        
        if user_doc.exists: # If the user document exists
            if user_doc.to_dict()['email'] == email:    # If the email address matches the email address in the user document
                if totp_verify(request.form['totp'], totp_secret):  # If the OTP is verified
                    user_ref.update({'password': base64.b64encode(new_password.encode("utf-8"))})  # Update the password field of the user document
                    return redirect(url_for('login'))   # Redirect to the login page
                else:   # If the OTP is not verified
                    return 'Invalid OTP'    # Return a message indicating that the OTP is invalid
            else:
                return 'Invalid email address'  # Return a message indicating that the email address is invalid
        else:
            return 'No user found with the provided username.'  # Return a message indicating that no user was found with the provided username
    return render_template('forgotpassword.html')    # Render the forgot_password.html template     



@app.route('/logout')   # Define the route for the logout page
@login_required # Use the login_required decorator to require the user to be logged in
def logout():   # Define the logout function
    logout_user()   # Log the user out
    return redirect(url_for('index'))   # Redirect to the index page



@app.route('/dashboard', methods=['GET', 'POST'])   # Define the route for the dashboard page
@login_required # Use the login_required decorator to require the user to be logged in
def dashboard():    # Define the dashboard function
    # Get user's budget entries
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    records_ref = db.collection('users').document(user_id).collection('records')    # Create a reference to the user's records collection
    records = records_ref.get() # Get the records from the user's records collection
    
    earnings = 0.0  # Initialize the earnings variable to 0.0
    expenses = 0.0  # Initialize the expenses variable to 0.0
    for record in records:  # Iterate over the records
        record_data = record.to_dict()  # Convert the record to a dictionary
        if record_data['Date']: # If the record has a Date field
            if record_data['type'] == 'credit':   # If the record type is credit
                earnings += float(record_data['amount'])    # Add the amount to the earnings variable
            elif record_data['type'] == 'debit':    # If the record type is debit
                expenses += float(record_data['amount'])    # Add the amount to the expenses variable

    # Fetch bill reminders
    reminders_ref = db.collection('users').document(user_id).collection('bill_reminders').get()   # Create a reference to the user's bill reminders collection
    reminders = [reminder.to_dict() for reminder in reminders_ref]  # Get the bill reminders from the user's bill reminders collection

    # Update due dates for bill reminders
    for reminder in reminders:  # Iterate over the bill reminders
        due_date_str = reminder['due_date'] # Get the due_date field from the reminder
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')  # Convert the due_date string to a datetime object
        recurrence = reminder['recurrence'] # Get the recurrence field from the reminder
        
        if due_date < datetime.now():   # If the due date has passed
            if recurrence == 'daily':   # If the recurrence is daily
                delta = timedelta(days=1)   # Set the delta to 1 day
            elif recurrence == 'weekly':    # If the recurrence is weekly
                delta = timedelta(weeks=1)  # Set the delta to 1 week
            elif recurrence == 'monthly':   # If the recurrence is monthly
                delta = timedelta(days=30)   # Set the delta to 30 days
            else:   # If the recurrence is not daily, weekly, or monthly
                delta = None    # Set the delta to None
            
            if delta:   # If the delta is not None
                while due_date < datetime.now():    # While the due date is less than the current date
                    due_date += delta   # Add the delta to the due date
                reminder_ref = db.collection('users').document(user_id).collection('bill_reminders').document(reminder['bill_name'])    # Create a reference to the reminder document
                reminder_ref.update({'due_date': due_date.strftime('%Y-%m-%d')})    # Update the due_date field of the reminder document

    # Fetch financial goals
    goals_ref = db.collection('users').document(user_id).collection('goals').get()  # Create a reference to the user's goals collection
    goals = [goal.to_dict() for goal in goals_ref]  # Get the goals from the user's goals collection

    balance_ref = db.collection('users').document(user_id)  # Create a reference to the user's document
    current_balance = balance_ref.get().to_dict().get('bank_balance', 0)    # Get the bank_balance field from the user's document

    if goals_ref != []: # If the goals collection is not empty
        earnings_goal = 0.0 # Initialize the earnings_goal variable to 0.0
        expenses_goal = 0.0 # Initialize the expenses_goal variable to 0.0
        for record in records:  # Iterate over the records
            record_data = record.to_dict()  # Convert the record to a dictionary
            if record_data['Date']: # If the record has a Date field
                if record_data['type'] == 'credit':
                    earnings_goal += float(record_data['amount'])   # Add the amount to the earnings_goal variable
                elif record_data['type'] == 'debit':
                    expenses_goal += float(record_data['amount'])   # Add the amount to the expenses_goal variable
        
        goal_ref = db.collection('users').document(user_id).collection('goals').get()   # Create a reference to the user's goals collection
        for goal in goal_ref:   # Iterate over the goals
            goal_data = goal.to_dict()  # Convert the goal to a dictionary
            if goal_data['target_amount']:  # If the goal has a target_amount field
                goals_doc = float(goal_data['target_amount'])   # Set the goals_doc variable to the target_amount field
                remaining_goal = goals_doc - current_balance if goals_doc is not None else None   # Set the remaining_goal variable to the difference between the target amount and the current balance
    else:   # If the goals collection is empty
        remaining_goal = None   # Set the remaining_goal variable to None
        earnings_goal = None    # Set the earnings_goal variable to None
        expenses_goal = None    # Set the expenses_goal variable to None 

    
    return render_template('dashboard.html', records=records, reminders=reminders, goals=goals, remaining_goal=remaining_goal, earnings_goal=earnings_goal, expenses_goal=expenses_goal, current_balance=current_balance, earnings=earnings, expenses=expenses)   # Render the dashboard.html template



@app.route('/verifypass', methods=['GET', 'POST'])   # Define the route for the verifypass page
@login_required # Use the login_required decorator to require the user to be logged in
def verifypass():   # Define the verifypass function
    if request.method == 'POST':    # If the request method is POST
        user_id = current_user.id   # Get the user_id attribute of the current_user instance
        password = request.form['password']
        pass64 = base64.b64encode(password.encode("utf-8")) # Encode the password using base64
        user_ref = db.collection('users').document(user_id)    # Create a reference to the user document
        totp_secret = user_ref.get().to_dict()['totp_secret']  # Get the totp_secret field from the user document
        user_pass = user_ref.get().to_dict()['password']   # Get the password field from the user document

        if pass64 == user_pass: # If the password is correct
            return totp_secret  # Return the totp_secret
        else:   # If the password is incorrect
            return 'Invalid password'   # Return a message indicating that the password is invalid
        
    return render_template('dashboard.html')    # Render the dashboard.html template



@app.route('/add_entry', methods=['POST'])  # Define the route for adding a budget entry
@login_required # Use the login_required decorator to require the user to be logged in
def add_entry():    # Define the add_entry function
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    date = request.form['date'] # Get the date from the form
    entry_type = request.form['type']   # Get the type from the form
    amount = float(request.form['amount'])  # Get the amount from the form
    reason = request.form['reason'] # Get the reason from the form
    description = request.form['description']   # Get the description from the form
    current_time = datetime.now().strftime('%H:%M:%S')  # Get the current time
    doc_name = date + '_' + current_time + '_' + entry_type.upper() + '_' + reason.upper()  # Create a document name
    record_ref = db.collection('users').document(user_id).collection('records').document(doc_name)  # Create a reference to the record document
    record_ref.set({
        'Date': date,
        'time': current_time,
        'type': entry_type,
        'amount': amount,
        'reason': reason,
        'description': description
    })  # Set the fields of the record document

    # Update current_balance based on entry type
    balance_ref = db.collection('users').document(user_id)  # Create a reference to the user's document
    balance = balance_ref.get().to_dict()['bank_balance']   # Get the bank_balance field from the user's document
    if entry_type == 'credit':  # If the entry type is credit
        new_balance = balance + amount  # Set the new_balance variable to the sum of the balance and the amount
    else:   # If the entry type is not credit
        new_balance = balance - amount  # Set the new_balance variable to the difference between the balance and the amount
    balance_ref.update({'bank_balance': new_balance})   # Update the bank_balance field of the user's document


    return redirect(url_for('dashboard'))   # Redirect to the dashboard page



# Route to delete a budget entry
@app.route('/delete_record/<record_id>', methods=['POST'])  # Define the route for deleting a budget entry
@login_required # Use the login_required decorator to require the user to be logged in
def delete_record(record_id):   # Define the delete_record function
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    record_ref = db.collection('users').document(user_id).collection('records').document(record_id)   # Create a reference to the record document
    record = record_ref.get().to_dict() # Get the record from the record document
    amount = float(record['amount'])    # Get the amount from the record
    entry_type = record['type'] # Get the type from the record

    # Delete the record
    record_ref.delete() 


    # Revert balance based on entry type
    balance_ref = db.collection('users').document(user_id)  # Create a reference to the user's document
    balance = balance_ref.get().to_dict()['bank_balance']   # Get the bank_balance field from the user's document
    if entry_type == 'credit':  # If the entry type is credit
        new_balance = balance - amount  # Set the new_balance variable to the difference between the balance and the amount
    else:   # If the entry type is not credit
        new_balance = balance + amount  # Set the new_balance variable to the sum of the balance and the amount
    balance_ref.update({'bank_balance': new_balance})   # Update the bank_balance field of the user's document

    return redirect(url_for('dashboard'))   



@app.route('/set_bill_reminder', methods=['POST'])  # Define the route for setting a bill reminder
@login_required # Use the login_required decorator to require the user to be logged in
def set_bill_reminder():    # Define the set_bill_reminder function
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    bill_name = request.form['bill_name']   # Get the bill_name from the form
    due_date_str = request.form['due_date'] # Get the due_date from the form
    recurrence = request.form['recurrence'] # Get the recurrence from the form
    amount = float(request.form['amount'])  # Get the amount from the form

    balance_ref = db.collection('users').document(user_id)  # Create a reference to the user's document
    balance = balance_ref.get().to_dict()['bank_balance']   # Get the bank_balance field from the user's document
    
    if balance >= amount:   # If the balance is greater than or equal to the amount
        reminder_ref = db.collection('users').document(user_id).collection('bill_reminders').document(bill_name)    # Create a reference to the bill reminder document
        reminder_ref.set({
            'bill_name': bill_name,
            'amount': amount,
            'due_date': due_date_str,
            'recurrence': recurrence
        })  # Set the fields of the bill reminder document

        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')  # Convert the due_date string to a datetime object
        
        # Check if due date has passed
        if due_date < datetime.now():   # If the due date has passed
            if recurrence == 'daily':   # If the recurrence is daily
                delta = timedelta(days=1)   # Set the delta to 1 day
            elif recurrence == 'weekly':    # If the recurrence is weekly
                delta = timedelta(weeks=1)  # Set the delta to 1 week
            elif recurrence == 'monthly':   # If the recurrence is monthly
                delta = timedelta(days=30)  # Set the delta to 30 days
            else:   # If the recurrence is not daily, weekly, or monthly
                delta = None    # Set the delta to None
            
            if delta:   # If the delta is not None
                while due_date < datetime.now():    # While the due date is less than the current date
                    due_date += delta   # Add the delta to the due date
        
        new_due_date_str = due_date.strftime('%Y-%m-%d')    # Convert the due_date to a string
        reminder_ref.update({   
            'due_date': new_due_date_str
        })  # Update the due_date field of the bill reminder document

        add_record(user_id, bill_name, new_due_date_str, amount)    # Call the add_record function 

            
    return redirect(url_for('dashboard'))   # Redirect to the dashboard page



@app.route('/delete_bill_reminder/<reminder_id>', methods=['POST']) # Define the route for deleting a bill reminder
@login_required # Use the login_required decorator to require the user to be logged in
def delete_bill_reminder(reminder_id):  # Define the delete_bill_reminder function
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    reminder_ref = db.collection('users').document(user_id).collection('bill_reminders').document(reminder_id)  # Create a reference to the bill reminder document
    reminder_ref.delete()   # Delete the bill reminder document
    return redirect(url_for('dashboard'))   # Redirect to the dashboard page



@app.route('/set_goal', methods=['POST'])   # Define the route for setting a financial goal
@login_required # Use the login_required decorator to require the user to be logged in
def set_goal(): # Define the set_goal function
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    goal_name = request.form['goal_name']   # Get the goal_name from the form
    target_amount = float(request.form['target_amount'])    # Get the target_amount from the form
    time = float(request.form['time_goal'])     # Get the time from the form
    
    goal_ref = db.collection('users').document(user_id).collection('goals').document(goal_name)   # Create a reference to the goal document
    goal_ref.set({
        'goal_name': goal_name,
        'target_amount': target_amount,
        'time': time
    })  # Set the fields of the goal document
    
    return redirect(url_for('dashboard'))   # Redirect to the dashboard page



@app.route('/delete_goal/<goal_id>', methods=['POST'])  # Define the route for deleting a financial goal
@login_required # Use the login_required decorator to require the user to be logged in
def delete_goal(goal_id):   # Define the delete_goal function
    user_id = current_user.id   # Get the user_id attribute of the current_user instance
    goal_ref = db.collection('users').document(user_id).collection('goals').document(goal_id)   # Create a reference to the goal document
    goal_ref.delete()   # Delete the goal document
    return redirect(url_for('dashboard'))   # Redirect to the dashboard page



@app.route('/aiguidance', methods=['POST', 'GET'])  # Define the route for AI guidance
@login_required # Use the login_required decorator to require the user to be logged in
def aiguidance():   # Define the aiguidance function
    prompt_parts = ["Please note that all amounts are in Indian Rupees (INR). Ensure accurate calculations are conducted for each recommendation. Where data is missing, make estimations to ensure completeness. Offer guidance in the following areas: Total Inflow (without detailed breakdown), Total Outflow (without detailed breakdown), Reminders (provide detailed advice and calculations), Goals (offer detailed advice and calculations), and Saving Money Efficiently (offer detailed advice). Now, Here are My Financial Records:"]   # Initialize the prompt_parts list with a prompt for the Generative AI model
    records_ref = db.collection('users').document(current_user.id).collection('records').get()  # Create a reference to the user's records collection
    reminders_ref = db.collection('users').document(current_user.id).collection('bill_reminders').get() # Create a reference to the user's bill reminders collection
    goals_ref = db.collection('users').document(current_user.id).collection('goals').get()  # Create a reference to the user's goals collection
    balance_ref = db.collection('users').document(current_user.id).get().to_dict()['bank_balance']  # Create a reference to the user's document and get the bank_balance field
    
    prompt_parts.append("My current balance is: " + str(balance_ref))   # Append the current balance to the prompt_parts list

    for record in records_ref:  # Iterate over the records
        record_data = record.to_dict()  # Convert the record to a dictionary
        prompt_parts.append("My current Transaction records are: " + str(record_data))  # Append the record to the prompt_parts list
    
    for reminder in reminders_ref:  # Iterate over the bill reminders
        reminder_data = reminder.to_dict()  # Convert the reminder to a dictionary
        prompt_parts.append("My current bills & EMIs are: " + str(reminder_data))   # Append the reminder to the prompt_parts list

    for goal in goals_ref:  # Iterate over the goals
        goal_data = goal.to_dict()  # Convert the goal to a dictionary
        prompt_parts.append("My current financial goals are: " + str(goal_data))    # Append the goal to the prompt_parts list


    response = model.generate_content(prompt_parts)  # Generate content using the prompt_parts list
    guidance = format_text_to_html(response.text)   # Format the response text to HTML


    return render_template('aiguidance.html', guidance=guidance)    # Render the aiguidance.html template



if __name__ == '__main__':  # If the script is executed
    # app.run(debug=True) # Run the app in debug mode
    webview.start()  # Start webview
    # app.run(host='0.0.0.0', port=5000)  # Run the app on port 5000
