from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import base64
import re
import google.generativeai as genai


app = Flask(__name__)
app.secret_key = 'uLKrvX,c*!gvkP7]~hRvo6H+:r"5PzD12"MMC#5s+[hO>PbByA=@{Q1=MampaB)'
login_manager = LoginManager()
login_manager.init_app(app)


# Initialize Firestore
cred = credentials.Certificate('quadbudget.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

genai.configure(api_key="AIzaSyCS665Uk0Ttvppz43y2i35DBcjGIVgeHzg")
generation_config = {
  "temperature": 0.9,
  "top_p": 1,
  "top_k": 1,
  "max_output_tokens": 2048,
}
safety_settings = [
  {
    "category": "HARM_CATEGORY_HARASSMENT",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
  },
  {
    "category": "HARM_CATEGORY_HATE_SPEECH",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
  },
  {
    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
  },
  {
    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
  },
]
model = genai.GenerativeModel(model_name="gemini-1.0-pro", generation_config=generation_config, safety_settings=safety_settings)


# Define User class
class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id

# Flask-Login user loader
@login_manager.user_loader
def load_user(user_id):
    return User(user_id)


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        password_confirm = request.form['repeated_password']
        bank_balance = request.form['bank_balance']
        pass64 = base64.b64encode(password.encode("utf-8"))
        
        # Check if passwords match
        if password == password_confirm:
            # Check if username is already taken
            if db.collection('users').document(username).get().exists:
                return 'Username already taken. Please choose another username.'
            
            # Create new user document
            user_ref = db.collection('users').document(username)
            user_ref.set({
                'username': username,
                'email': email,
                'password': pass64,
                'bank_balance': bank_balance
            })
            return redirect(url_for('index'))
        else:
            return 'Passwords do not match. Please try again.'
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        pass64 = base64.b64encode(password.encode("utf-8"))
        
        user_ref = db.collection('users').document(username)
        user_doc = user_ref.get()
        
        if not user_doc.exists or user_doc.to_dict()['password'] != pass64:
            return 'Invalid username or password'
        
        # Create a User instance and pass it to login_user
        user = User(user_id=username)  # Assuming User class expects user_id in its constructor
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    # Get user's budget entries
    user_id = current_user.id
    records_ref = db.collection('users').document(user_id).collection('records')
    records = records_ref.get()
    
    earnings = 0.0
    expenses = 0.0
    for record in records:
        record_data = record.to_dict()
        if record_data['Date']:
            if record_data['type'] == 'credit':
                earnings += float(record_data['amount'])
            elif record_data['type'] == 'debit':
                expenses += float(record_data['amount'])

    # Fetch bill reminders
    reminders_ref = db.collection('users').document(user_id).collection('bill_reminders').get()
    reminders = [reminder.to_dict() for reminder in reminders_ref]

    # Update due dates for bill reminders
    for reminder in reminders:
        due_date_str = reminder['due_date']
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        recurrence = reminder['recurrence']
        
        if due_date < datetime.now():
            if recurrence == 'daily':
                delta = timedelta(days=1)
            elif recurrence == 'weekly':
                delta = timedelta(weeks=1)
            elif recurrence == 'monthly':
                delta = timedelta(days=30)  # Approximation for monthly recurrence, adjust as needed
            else:
                delta = None
            
            if delta:
                while due_date < datetime.now():
                    due_date += delta
                reminder_ref = db.collection('users').document(user_id).collection('bill_reminders').document(reminder['bill_name'])
                reminder_ref.update({'due_date': due_date.strftime('%Y-%m-%d')})

    # Fetch financial goals
    goals_ref = db.collection('users').document(user_id).collection('goals').get()
    goals = [goal.to_dict() for goal in goals_ref]

    balance_ref = db.collection('users').document(user_id)
    current_balance = balance_ref.get().to_dict().get('bank_balance', 0)

    if goals_ref != []:
        earnings_goal = 0.0
        expenses_goal = 0.0
        for record in records:
            record_data = record.to_dict()
            if record_data['Date']:
                if record_data['type'] == 'credit':
                    earnings_goal += float(record_data['amount'])
                elif record_data['type'] == 'debit':
                    expenses_goal += float(record_data['amount'])
        
        goal_ref = db.collection('users').document(user_id).collection('goals').get()
        for goal in goal_ref:
            goal_data = goal.to_dict()
            if goal_data['target_amount']:
                goals_doc = float(goal_data['target_amount'])
                remaining_goal = goals_doc - current_balance if goals_doc is not None else None
    else:
        remaining_goal = None
        earnings_goal = None
        expenses_goal = None    

    
    return render_template('dashboard.html', records=records, reminders=reminders, goals=goals, remaining_goal=remaining_goal, earnings_goal=earnings_goal, expenses_goal=expenses_goal, current_balance=current_balance, earnings=earnings, expenses=expenses)


@app.route('/add_entry', methods=['POST'])
@login_required
def add_entry():
    user_id = current_user.id
    date = request.form['date']
    entry_type = request.form['type']
    amount = float(request.form['amount'])
    reason = request.form['reason']
    description = request.form['description']
    current_time = datetime.now().strftime('%H:%M:%S')
    doc_name = date + '_' + current_time + '_' + entry_type.upper()
    record_ref = db.collection('users').document(user_id).collection('records').document(doc_name)
    record_ref.set({
        'Date': date,
        'time': current_time,
        'type': entry_type,
        'amount': amount,
        'reason': reason,
        'description': description
    })

    # Update current_balance based on entry type
    balance_ref = db.collection('users').document(user_id)
    balance = balance_ref.get().to_dict()['bank_balance']
    if entry_type == 'credit':
        new_balance = balance + amount
    else:
        new_balance = balance - amount
    balance_ref.update({'bank_balance': new_balance})


    return redirect(url_for('dashboard'))


# Route to delete a budget entry
@app.route('/delete_record/<record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    user_id = current_user.id
    record_ref = db.collection('users').document(user_id).collection('records').document(record_id)
    record = record_ref.get().to_dict()
    amount = float(record['amount'])
    entry_type = record['type']

    # Delete the record
    record_ref.delete()


    # Revert balance based on entry type
    balance_ref = db.collection('users').document(user_id)
    balance = balance_ref.get().to_dict()['bank_balance']
    if entry_type == 'credit':
        new_balance = balance - amount
    else:
        new_balance = balance + amount
    balance_ref.update({'bank_balance': new_balance})

    return redirect(url_for('dashboard'))


def add_record(user_id, bill_name, due_date, amount):
    # Add a record entry for the bill reminder
    record_ref = db.collection('users').document(user_id).collection('records').document()
    record_ref.set({
        'Date': due_date,
        'type': 'debit',  # Assuming bill reminder is a debit
        'amount': amount,      
        'reason': bill_name,
        'description': 'Automatically generated record for bill: ' + bill_name
    })

@app.route('/set_bill_reminder', methods=['POST'])
@login_required
def set_bill_reminder():
    # Set a bill reminder
    user_id = current_user.id
    bill_name = request.form['bill_name']
    due_date_str = request.form['due_date']
    recurrence = request.form['recurrence']
    amount = float(request.form['amount'])

    balance_ref = db.collection('users').document(user_id)
    balance = balance_ref.get().to_dict()['bank_balance']
    
    if balance >= amount:
        # Store bill reminder in the database
        reminder_ref = db.collection('users').document(user_id).collection('bill_reminders').document(bill_name)
        reminder_ref.set({
            'bill_name': bill_name,
            'amount': amount,
            'due_date': due_date_str,
            'recurrence': recurrence
        })

        due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        
        # Check if due date has passed
        if due_date < datetime.now():
            if recurrence == 'daily':
                delta = timedelta(days=1)
            elif recurrence == 'weekly':
                delta = timedelta(weeks=1)
            elif recurrence == 'monthly':
                # Approximation for monthly recurrence, adjust as needed
                delta = timedelta(days=30)
            else:
                delta = None
            
            if delta:
                while due_date < datetime.now():
                    due_date += delta
        
        new_due_date_str = due_date.strftime('%Y-%m-%d')
        reminder_ref.update({
            'due_date': new_due_date_str
        })

        # Add record
        add_record(user_id, bill_name, new_due_date_str, amount)   

            
    return redirect(url_for('dashboard'))

@app.route('/delete_bill_reminder/<reminder_id>', methods=['POST'])
@login_required
def delete_bill_reminder(reminder_id):
    user_id = current_user.id
    reminder_ref = db.collection('users').document(user_id).collection('bill_reminders').document(reminder_id)
    reminder_ref.delete()
    return redirect(url_for('dashboard'))

@app.route('/set_goal', methods=['POST'])
@login_required
def set_goal():
    # Set a financial goal
    user_id = current_user.id
    goal_name = request.form['goal_name']
    target_amount = float(request.form['target_amount'])
    time = float(request.form['time_goal'])
    
    goal_ref = db.collection('users').document(user_id).collection('goals').document(goal_name)
    goal_ref.set({
        'goal_name': goal_name,
        'target_amount': target_amount,
        'time': time
    })
    
    return redirect(url_for('dashboard'))

@app.route('/delete_goal/<goal_id>', methods=['POST'])
@login_required
def delete_goal(goal_id):
    user_id = current_user.id
    goal_ref = db.collection('users').document(user_id).collection('goals').document(goal_id)
    goal_ref.delete()
    return redirect(url_for('dashboard'))
    
def format_text_to_html(text):
    # Replace bold markdown with HTML bold tags
    formatted_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Replace bullet points with list items
    formatted_text = re.sub(r'^\* (.*?)$', r'<li>\1</li>', formatted_text, flags=re.MULTILINE)
    # Replace numbers with list items
    formatted_text = re.sub(r'^(\d+)\. (.*?)$', r'<li>\1. \2</li>', formatted_text, flags=re.MULTILINE)
    # Add appropriate tags for sections
    formatted_text = re.sub(r'^<b>(.*?)</b>(.*?)<b>', r'<h2>\1</h2>\2<b>', formatted_text, flags=re.MULTILINE)
    # Add paragraph tags
    formatted_text = re.sub(r'^(?![\s*<])(.*)$', r'<p>\1</p>', formatted_text, flags=re.MULTILINE)
    return formatted_text


@app.route('/aiguidance', methods=['POST', 'GET'])
@login_required
def aiguidance():
    prompt_parts = ["Please note that all amounts are in Indian Rupees (INR). Ensure accurate calculations are conducted for each recommendation. Where data is missing, make estimations to ensure completeness. Offer guidance in the following areas: Total Inflow (without detailed breakdown), Total Outflow (without detailed breakdown), Reminders (provide detailed advice and calculations), Goals (offer detailed advice and calculations), and Saving Money Efficiently (offer detailed advice). Now, Here are My Financial Records:"]
    records_ref = db.collection('users').document(current_user.id).collection('records').get()
    reminders_ref = db.collection('users').document(current_user.id).collection('bill_reminders').get()
    goals_ref = db.collection('users').document(current_user.id).collection('goals').get()
    balance_ref = db.collection('users').document(current_user.id).get().to_dict()['bank_balance']
    
    prompt_parts.append("My current balance is: " + str(balance_ref))

    for record in records_ref:
        record_data = record.to_dict()
        prompt_parts.append("My current Transaction records are: " + str(record_data))
    
    for reminder in reminders_ref:
        reminder_data = reminder.to_dict()
        prompt_parts.append("My current bills & EMIs are: " + str(reminder_data))

    for goal in goals_ref:
        goal_data = goal.to_dict()
        prompt_parts.append("My current financial goals are: " + str(goal_data))


    response = model.generate_content(prompt_parts)
    guidance = format_text_to_html(response.text)


    with open('guidance.txt', 'w', encoding='utf-8') as file:
        file.write(guidance)


    return render_template('aiguidance.html', guidance=guidance)


if __name__ == '__main__':
    app.run(debug=True)
