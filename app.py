from flask import Flask, request, jsonify, send_file, render_template, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from functools import wraps
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
import os
import re
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

app = Flask(__name__)

# Configuration de la base de données
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dataclean.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-super-secret-key')

# Configuration des dossiers
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['CLEANED_FOLDER'] = os.getenv('CLEANED_FOLDER', 'cleaned')

# Créer les dossiers nécessaires
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['CLEANED_FOLDER'], exist_ok=True)

# Initialisation de SQLAlchemy et Flask-Migrate
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Modèles
class User(db.Model):
    __tablename__ = 'users'  # Avoid PostgreSQL reserved word
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    cleaned_files = db.relationship('CleanedFile', backref='user', lazy=True)

class CleanedFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Décorateur pour vérifier l'authentification
def is_logged_in(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'loggedin' not in session:
            flash('Veuillez vous connecter pour accéder à cette page', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
        else:
            user = User.query.filter_by(email=email).first()
            
            if user:
                flash('Cet email est déjà utilisé', 'danger')
            elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
                flash('Adresse email invalide', 'danger')
            elif len(password) < 6:
                flash('Le mot de passe doit contenir au moins 6 caractères', 'danger')
            else:
                hashed_password = generate_password_hash(password)
                new_user = User(name=name, email=email, password=hashed_password)
                db.session.add(new_user)
                db.session.commit()
                flash('Inscription réussie! Vous pouvez maintenant vous connecter', 'success')
                return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['loggedin'] = True
            session['id'] = user.id
            session['name'] = user.name
            flash('Connexion réussie!', 'success')
            return redirect(url_for('profile'))
        else:
            flash('Email ou mot de passe incorrect', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('name', None)
    return redirect(url_for('index'))

@app.route('/profile')
@is_logged_in
def profile():
    user = User.query.get(session['id'])
    cleaned_files = CleanedFile.query.filter_by(user_id=session['id']).order_by(CleanedFile.created_at.desc()).all()
    return render_template('profile.html', user=user, cleaned_files=cleaned_files)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv', 'xlsx', 'json'}

def clean_data(df):
    # Supprimer les doublons
    df = df.drop_duplicates()
    
    # Gérer les valeurs manquantes
    numeric_columns = df.select_dtypes(include=[np.number]).columns
    categorical_columns = df.select_dtypes(exclude=[np.number]).columns
    
    # Pour les colonnes numériques, remplacer par la médiane
    for col in numeric_columns:
        df[col] = df[col].fillna(df[col].median())
    
    # Pour les colonnes catégorielles, remplacer par le mode
    for col in categorical_columns:
        df[col] = df[col].fillna(df[col].mode()[0] if not df[col].mode().empty else 'Unknown')
    
    # Standardisation des colonnes numériques
    scaler = StandardScaler()
    df[numeric_columns] = scaler.fit_transform(df[numeric_columns])
    
    return df

@app.route('/api/clean', methods=['POST'])
@is_logged_in
def api_clean():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Aucun fichier fourni'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nom de fichier vide'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Type de fichier non autorisé'}), 400
    
    try:
        # Essayer plusieurs encodages courants
        encodings_to_try = ['utf-8', 'latin1', 'ISO-8859-1', 'cp1252']
        
        for encoding in encodings_to_try:
            try:
                file.stream.seek(0)  # Réinitialiser le pointeur du fichier
                df = pd.read_csv(file, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return jsonify({
                'success': False,
                'error': "Impossible de décoder le fichier avec les encodages standards"
            }), 400
        
        cleaned_df = clean_data(df)
        
        filename = secure_filename(file.filename)
        output_filename = f"cleaned_{filename}"
        output_path = os.path.join(app.config['CLEANED_FOLDER'], output_filename)
        cleaned_df.to_csv(output_path, index=False, encoding='utf-8')
        
        new_cleaned_file = CleanedFile(
            user_id=session['id'],
            original_name=file.filename,
            filename=output_filename
        )
        db.session.add(new_cleaned_file)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Fichier nettoyé avec succès',
            'filename': output_filename,
            'columns': list(cleaned_df.columns),
            'row_count': len(cleaned_df)
        })
       
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Erreur lors du traitement: {str(e)}"
        }), 500

@app.route('/download/<filename>')
@is_logged_in
def download_file(filename):
    cleaned_file = CleanedFile.query.filter_by(filename=filename, user_id=session['id']).first()
    if cleaned_file:
        return send_file(
            os.path.join(app.config['CLEANED_FOLDER'], filename),
            as_attachment=True,
            download_name=filename
        )
    return jsonify({'success': False, 'error': 'Fichier non trouvé'}), 404

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)