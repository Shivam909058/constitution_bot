import PyPDF2
import re
import nltk
from nltk.corpus import stopwords
from openai import OpenAI
import chromadb
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from tqdm import tqdm
import tiktoken
import logging
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
import time
import os
from dotenv import load_dotenv
import json
import psutil
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from datetime import datetime


load_dotenv()


nltk.download('stopwords')
stop_words = set(stopwords.words('english'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('chatbot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Book Chatbot API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://seashell-app-u2veg.ondigitalocean.app/"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", StaticFiles(directory="static"), name="static")


client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))



chroma_client = chromadb.PersistentClient(
    path="/tmp/chroma_db"  
)
collection = chroma_client.get_or_create_collection(
    name="book_embeddings",
    metadata={"hnsw:space": "cosine"}
)

def log_memory_usage():
    """Log current memory usage"""
    process = psutil.Process()
    logger.info(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")

def save_progress(stage, completed=False):
    """Save processing progress to file"""
    with open('progress.json', 'w') as f:
        json.dump({'stage': stage, 'completed': completed}, f)

def pdf_to_text(pdf_path):
    """Convert PDF to text with progress tracking"""
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            total_pages = len(pdf_reader.pages)
            logger.info(f"Processing {total_pages} pages")
            
            for page_num in tqdm(range(total_pages), desc="Converting PDF"):
                page = pdf_reader.pages[page_num]
                text += page.extract_text()
                
                if page_num % 50 == 0:
                    log_memory_usage()
        
        return text
    except Exception as e:
        logger.error(f"Error in PDF conversion: {e}")
        raise

def clean_text(text):
    """Clean and preprocess text"""
    logger.info("Cleaning text...")
    
    
    text = re.sub(r'[^A-Za-z\s]', '', text)
    
   
    text = text.lower()
    
   
    words = text.split()
    words = [word for word in words if word not in stop_words]
    
    return ' '.join(words)

def chunk_text(text, max_tokens=1000):
    """Chunk text based on token count"""
    logger.info("Chunking text...")
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    chunks = []
    current_chunk = []
    current_length = 0
    
    for token in tqdm(tokens, desc="Chunking"):
        current_chunk.append(token)
        current_length += 1
        
        if current_length >= max_tokens:
            chunk_text = encoding.decode(current_chunk)
            chunks.append(chunk_text)
            current_chunk = []
            current_length = 0
    
    if current_chunk:
        chunk_text = encoding.decode(current_chunk)
        chunks.append(chunk_text)
    
    logger.info(f"Created {len(chunks)} chunks")
    return chunks

def create_embeddings_batch(chunks, batch_size=100):
    """Create embeddings in batches"""
    all_embeddings = []
    retry_delay = 60  # seconds
    max_retries = 3
    
    for i in tqdm(range(0, len(chunks), batch_size), desc="Creating embeddings"):
        batch = chunks[i:i + batch_size]
        for attempt in range(max_retries):
            try:
                response = client.embeddings.create(
                    input=batch,
                    model="text-embedding-3-small"
                )
                batch_embeddings = [e.embedding for e in response.data]
                all_embeddings.extend(batch_embeddings)
                break
            except Exception as e:
                logger.error(f"Error processing batch {i}, attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise
    
    return all_embeddings

def store_embeddings_in_db(text_chunks, embeddings, batch_size=500):
    """Store embeddings in ChromaDB"""
    for i in tqdm(range(0, len(text_chunks), batch_size), desc="Storing in ChromaDB"):
        batch_texts = text_chunks[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        batch_ids = [f"chunk_{j}" for j in range(i, i + len(batch_texts))]
        batch_metadata = [{"chunk_id": j, "source": "book"} for j in range(i, i + len(batch_texts))]
        
        collection.add(
            documents=batch_texts,
            embeddings=batch_embeddings,
            ids=batch_ids,
            metadatas=batch_metadata
        )

def retrieve_relevant_text(query, n_results=5):
    """Retrieve relevant text chunks"""
    query_embedding = create_embeddings_batch([query])[0]
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )
    
    documents = results['documents'][0]
    distances = results['distances'][0]
    
    # Combine chunks with distance scores
    context = "\n\n".join([f"[Relevance: {1 - dist:.2f}] {doc}" 
                          for doc, dist in zip(documents, distances)])
    
    return context

def generate_chatbot_response(relevant_text, user_query):
    """Generate response using GPT-4"""
    prompt = f"""Based on the following context from the book, please answer the user's question. 
    If the answer cannot be found in the context, say so.
    
    Context: {relevant_text}
    
    Question: {user_query}
    
    Answer:"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are a knowledgeable assistant helping users understand the content of a book. Provide accurate, relevant information based on the context provided."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "I apologize, but I encountered an error generating the response. Please try again."

class QueryRequest(BaseModel):
    query: str

@app.post("/query/")
async def query_chatbot(request: QueryRequest):
    try:
        query = request.query
        relevant_text = retrieve_relevant_text(query)
        chatbot_response = generate_chatbot_response(relevant_text, query)
        return {"response": chatbot_response, "status": "success"}
    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")  # Add detailed logging
        return {
            "response": "Sorry, I encountered an error while processing your request.",
            "status": "error",
            "error_details": str(e)  
        }

@app.get("/")
async def read_root():
    return FileResponse('templates/index.html')

@app.get("/static/script.js")
async def serve_script():
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return FileResponse(
        'static/script.js',
        media_type='application/javascript',
        headers=headers
    )

def main():
    try:
        # Initialize necessary components
        pdf_path = 'cons.pdf'
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found: {pdf_path}")
            return
            
        # Process the book
        book_text = pdf_to_text(pdf_path)
        cleaned_text = clean_text(book_text)
        text_chunks = chunk_text(cleaned_text)
        
        # Check if data exists in ChromaDB
        if collection.count() == 0:
            logger.info("Initializing database with book content...")
            embeddings = create_embeddings_batch(text_chunks)
            store_embeddings_in_db(text_chunks, embeddings)
            
        logger.info("Application ready!")
        
    except Exception as e:
        logger.error(f"Initialization error: {str(e)}")
        raise

if __name__ == "__main__":
    main()
