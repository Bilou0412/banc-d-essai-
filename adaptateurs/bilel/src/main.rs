//! Adaptateur du green Bilel pour le banc V5.
//!
//! Entrée (stdin) : `{"pages": ["texte page 1", "texte page 2", ...]}`.
//! Sortie (stdout) : le `Facts` de BuildForge sérialisé tel quel (11 faits, statuts, valeurs, citations).
//! Le serveur llama.cpp (NuExtract 3, température 0) est lu dans `EXTRACTOR_URL`.

use std::{io::Read, time::Duration};

use buildforge_server::dce::{
    extractor::LlamaServer,
    facts,
    text::{Document, Method, Page},
};

#[tokio::main]
async fn main() {
    let mut entree = String::new();
    std::io::stdin().read_to_string(&mut entree).expect("stdin");
    let v: serde_json::Value = serde_json::from_str(&entree).expect("JSON");
    let pages = v["pages"].as_array().expect("pages");
    let document = Document {
        pages: pages
            .iter()
            .enumerate()
            .map(|(i, t)| Page {
                number: i as u32 + 1,
                label: None,
                method: Method::Text,
                text: t.as_str().unwrap_or_default().to_string(),
            })
            .collect(),
    };
    let url = std::env::var("EXTRACTOR_URL").unwrap_or_else(|_| "http://127.0.0.1:8080".into());
    let delai: u64 = std::env::var("DELAI_S").ok().and_then(|s| s.parse().ok()).unwrap_or(3600);
    let serveur = LlamaServer::new(&url, None, Duration::from_secs(delai)).expect("URL");
    let debut = std::time::Instant::now();
    match facts::extract(&document, &serveur, facts::DEFAULT_CHUNK_CHARS).await {
        Ok(f) => {
            let mut j = serde_json::to_value(&f).expect("sérialisable");
            j["secondes"] = serde_json::json!(debut.elapsed().as_secs_f64());
            println!("{}", j);
        }
        Err(e) => {
            println!("{}", serde_json::json!({"erreur": e.to_string(), "secondes": debut.elapsed().as_secs_f64()}));
        }
    }
}
