"""Image Processor for Multimodal RAG and Landing Page Generation

Analyzes images using vision models and stores them in vector database
with YAML-formatted metadata for landing page generation context.
"""

import os
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.documents import Document
from vector_store import get_vector_store_manager, COLLECTIONS, INDEXES
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    Image processor for code generation and multimodal RAG.

    Analyzes images using vision models (Grok-4-fast) and stores them in MongoDB Atlas
    vector database with YAML-formatted metadata for semantic retrieval.

    Attributes:
        vs_manager: Vector store manager instance
        vector_store: MongoDB vector store for image embeddings
        vision_model: Initialized vision model (Grok-4-fast)
        openrouter_api_key: API key for OpenRouter
        VISION_PROMPT: Template for image analysis
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        vector_collection: Optional[str] = None,
        mongo_uri: Optional[str] = None,
        db_name: str = "langchain_game_agent",
        openrouter_api_key: Optional[str] = None,
    ):
        """
        Initialize the ImageProcessor.

        Args:
            openai_api_key: OpenAI API key for embeddings (defaults to env OPENAI_API_KEY)
            vector_collection: MongoDB collection name (defaults to COLLECTIONS["image"])
            mongo_uri: MongoDB connection URI (defaults to env MONGODB_CONNECTION_STRING)
            db_name: Database name for vector store
            openrouter_api_key: OpenRouter API key for vision model (defaults to env OPENROUTER_API_KEY)

        Raises:
            ValueError: If required API keys are not provided
        """
        vector_collection = vector_collection or COLLECTIONS["image"]

        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY required")

        self.vs_manager = get_vector_store_manager(
            mongo_uri=mongo_uri, db_name=db_name, openai_api_key=api_key
        )

        self.vector_store = self.vs_manager.get_vector_store(
            collection_name=vector_collection, index_name=INDEXES["image"]
        )

        self.openrouter_api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY required")

        self.vision_model = init_chat_model(
            model="x-ai/grok-4-fast",
            model_provider="openai",
            api_key=self.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0.1,
            max_tokens=1024,
            timeout=120,
        )

        self.VISION_PROMPT = """Analyze this image comprehensively for landing page generation and multimodal RAG. 
DETECT image type automatically, then provide PERFECT analysis in this EXACT YAML format (10-12 lines max, no code blocks, no extra text):
---
Image Type: [design|screenshot|diagram|photo|chart|code|document|other]
Purpose: [exact purpose - dashboard|landing|login|flowchart|ERD|photo|etc]

## VISUAL STRUCTURE
Layout: [header+sidebar|hero+grid|navbar+cards|flow+nodes|etc]
Components: [navbar,buttons,cards,charts,tables,forms,nodes,lines,shapes]
Colors: [primary:#hex,accent:#hex,bg:#hex,important:#hex]
Resolution: [width x height px] | Aspect: [16:9|1:1|etc]

## STYLE & THEME  
Theme: [modern|dark|minimal|gradient|glassmorphism|flat|3D]
Style: [rounded|sharp|neumorphic|sketch|professional|casual]
Typography: [font styles, sizes, hierarchy]

## CONTENT ANALYSIS
Main Subject: [primary focus/object/person]
Key Elements: [charts data, text content, people, objects, relationships]
Actions/Interactions: [clickable areas, data flow, user paths]

## TECHNICAL DETAILS
Tech Indicators: [React|Tailwind|Bootstrap|charts lib|Figma|etc]
Responsive: [yes/no|mobile hints|breakpoints]
Accessibility: [color contrast|text sizes|patterns]

Summary: [2 sentences: what this image represents + codegen relevance]

---
RULES:
1. Use EXACT hex colors (#1e40af) from image
2. Be specific: "3-column grid" not "grid"
3. For diagrams: describe nodes/arrows/dataflow
4. For screenshots: identify app type + features
5. For photos: describe scene + mood + composition
6. Always include filename at end

Filename: {filename}
"""

    async def process_image(
        self,
        s3_url: str,
        filename: str,
        session_id: str,
    ) -> Dict[str, str]:
        """
        Analyze image with vision model and store in vector database.

        Processes image using Grok-4-fast vision model to extract comprehensive metadata
        in YAML format, then stores the analysis in MongoDB Atlas for semantic retrieval.
        Includes automatic retry logic for timeout errors.

        Args:
            s3_url: Public URL of the image (S3, CDN, etc.)
            filename: Original filename of the image
            session_id: Session identifier for grouping related images

        Returns:
            Dictionary with status, filename, s3_url, img_analysis, and processing_time.
            On error, includes 'error' field instead of 'img_analysis'.
        """
        logger.info(f"Processing: {filename} (session: {session_id[:8]})")

        prompt = self.VISION_PROMPT.format(filename=filename)

        try:
            for attempt in range(3):
                try:
                    response = await self.vision_model.ainvoke(
                        [
                            HumanMessage(
                                content=[
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": s3_url,
                                            "detail": "medium",
                                        },
                                    },
                                ]
                            )
                        ]
                    )

                    analysis_text = response.content.strip()

                    for marker in ["```yaml", "```", "```json"]:
                        if marker in analysis_text:
                            start = analysis_text.find(marker) + len(marker)
                            end = analysis_text.find("```", start)
                            if end > start:
                                analysis_text = analysis_text[start:end].strip()

                    doc = Document(
                        page_content=f"Image Analysis:\n{analysis_text}",
                        metadata={
                            "session_id": session_id,
                            "content_type": "image",
                            "filename": filename,
                            "s3_url": s3_url,
                            "img_analysis": analysis_text,
                            "created_at": datetime.now().isoformat(),
                        },
                    )

                    self.vector_store.add_documents([doc])

                    logger.info(f"Stored {filename} in vector DB")

                    return {
                        "status": "success",
                        "filename": filename,
                        "s3_url": s3_url,
                        "img_analysis": analysis_text,
                    }

                except Exception as e:
                    if "timeout" in str(e).lower() and attempt < 2:
                        wait_time = 2**attempt
                        logger.warning(
                            f"Timeout on attempt {attempt + 1}, retrying in {wait_time}s"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    raise e

        except Exception as e:
            logger.error(f"Failed to process {filename}: {e}")

            return {
                "status": "error",
                "filename": filename,
                "s3_url": s3_url,
                "error": str(e),
            }

    async def retrieve_images(
        self,
        query: str,
        session_id: str,
        max_images: int = 3,
        min_score: float = 0.78,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant images from vector database based on semantic query.

        Performs similarity search on stored images and returns those matching
        the query within the specified session, filtered by minimum score.

        Args:
            query: Natural language query describing desired images
            session_id: Session identifier to filter images
            max_images: Maximum number of images to return
            min_score: Minimum similarity score threshold (0.0-1.0)

        Returns:
            List of dictionaries containing filename, s3_url, img_analysis,
            score, relevance, and created_at for each matching image.
        """
        logger.info(f"Retrieving: '{query}' (session: {session_id[:8]})")

        try:
            results = self.vector_store.similarity_search_with_score(
                query, k=max_images * 3
            )
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

        images = []
        for doc, score in results:
            meta = doc.metadata

            if (
                meta.get("session_id") == session_id
                and meta.get("content_type") == "image"
                and score >= min_score
            ):
                images.append(
                    {
                        "filename": meta.get("filename", ""),
                        "s3_url": meta.get("s3_url", ""),
                        "img_analysis": meta.get("img_analysis", ""),
                        "score": float(score),
                        "relevance": "high" if score > 0.85 else "medium",
                        "created_at": meta.get("created_at", ""),
                    }
                )

                if len(images) >= max_images:
                    break

        logger.info(f"Found {len(images)} images (min_score: {min_score})")
        return images

    async def get_session_images(self, session_id: str) -> List[Dict[str, str]]:
        """
        Get all images associated with a specific session.

        Retrieves metadata for all images belonging to the given session,
        useful for listing available images to agents or users.

        Args:
            session_id: Session identifier to filter images

        Returns:
            List of dictionaries containing filename, s3_url, and created_at
            for each image in the session.
        """
        logger.info(f"Listing images for session: {session_id[:8]}")

        try:
            all_docs = self.vector_store.similarity_search("image", k=100)
        except Exception as e:
            logger.error(f"Failed to retrieve session images: {e}")
            return []

        session_images = []
        for doc in all_docs:
            meta = doc.metadata
            if (
                meta.get("session_id") == session_id
                and meta.get("content_type") == "image"
            ):
                session_images.append(
                    {
                        "filename": meta.get("filename", ""),
                        "s3_url": meta.get("s3_url", ""),
                        "created_at": meta.get("created_at", ""),
                    }
                )

        logger.info(f"Found {len(session_images)} images in session")
        return session_images
