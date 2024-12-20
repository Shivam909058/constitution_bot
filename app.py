import PyPDF2
import re
import nltk
from nltk.corpus import stopwords
from openai import OpenAI
import chromadb
from fastapi import FastAPI, BackgroundTasks
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
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# Download stopwords for text processing
nltk.download('stopwords')
stop_words = set(stopwords.words('english'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('chatbot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Book Chatbot API")

# Handle CORS issues
allowed_origins = os.getenv("CORS_ORIGINS", "https://bot-test-weld-seven.vercel.app").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

@app.options("/query")  # Handle OPTIONS preflight request
async def options_query():
    return {}

# Initialize OpenAI and ChromaDB clients
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(
    name="book_embeddings",
    metadata={"hnsw:space": "cosine"}
)

# Utility functions
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

def create_embeddings_batch(chunks, batch_size=20):
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
                    retry_delay *= 2
                    time.sleep(retry_delay)
                else:
                    raise
    
    return all_embeddings

def store_embeddings_in_db(text_chunks, embeddings, batch_size=100):
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
                {"role": "system", "content": "You are a knowledgeable assistant helping users understand the content of a book."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "I apologize, but I encountered an error generating the response. Please try again."

# Pydantic model for query requests
class QueryRequest(BaseModel):
    query: str

# API endpoint for querying the chatbot
@app.post("/query/")
async def query_chatbot(request: QueryRequest, background_tasks: BackgroundTasks):
    """API endpoint for querying the chatbot"""
    try:
        query = request.query
        relevant_text = retrieve_relevant_text(query)
        chatbot_response = generate_chatbot_response(relevant_text, query)
        return {"response": chatbot_response, "status": "success"}
    except Exception as e:
        logger.error(f"Error processing query: {e}")
        return {"response": "An error occurred processing your query.", "status": "error", "error": str(e)}

# Root endpoint for testing
@app.get("/")
async def read_root():
    return "Hello world"

# Main function to process book and initialize chatbot
def main():
    """Main function to process book and initialize chatbot"""
    try:
        logger.info("Starting book processing...")
        log_memory_usage()
        
        # Step 1: Convert PDF to text
        save_progress("pdf_conversion", False)
        pdf_path = 'cons.pdf'
        book_text = pdf_to_text(pdf_path)
        save_progress("pdf_conversion", True)
        
        # Step 2: Clean the text
        save_progress("text_cleaning", False)
        cleaned_text = clean_text(book_text)
        save_progress("text_cleaning", True)
        
        # Step 3: Chunk the text
        save_progress("text_chunking", False)
        text_chunks = chunk_text(cleaned_text)
        save_progress("text_chunking", True)
        
        # Step 4: Generate embeddings
        save_progress("embedding_generation", False)
        embeddings = create_embeddings_batch(text_chunks)
        save_progress("embedding_generation", True)
        
        # Step 5: Store in ChromaDB
        save_progress("database_storage", False)
        store_embeddings_in_db(text_chunks, embeddings)
        save_progress("database_storage", True)
        
        logger.info("Processing complete! The chatbot is ready to use.")
        log_memory_usage()
        
    except Exception as e:
        logger.error(f"Error in main process: {e}")

if __name__ == "__main__":
    main()
