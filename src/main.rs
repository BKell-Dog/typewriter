use eframe::egui;
use rfd::FileDialog;
use std::fs;
use dirs;
use rodio::{Decoder, OutputStream};

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions::default();
    eframe::run_native(
        "Typwriter",
        options,
        Box::new(|_cc| {
            let (stream, stream_handle) = rodio::OutputStream::try_default().unwrap();
            let sound_file = std::fs::read("../typewriter_click.wav").unwrap();  // Read the file bytes

            Ok(Box::new(Typewriter {
                text: String::new(),
                file_path: None,
                last_key: None,
                audio_sink: stream_handle, // Initialize the audio_sink with stream_handle
                sound_bytes: sound_file,  // Store the sound bytes from the file
            }))
        })
    )
}

struct Typewriter {
    text: String,
    file_path: Option<std::path::PathBuf>,
    last_key: Option<egui::Key>,
    audio_sink: rodio::OutputStreamHandle,
    sound_bytes: Vec<u8>,
}

impl Default for Typewriter {
    fn default() -> Self {
        Self {
            text: String::new(),
            file_path: None,
            last_key: None,
        }
    }
}


impl eframe::App for Typewriter {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {

        // Key press detection
        for key in egui::Key::ALL {
            if ctx.input(|i| i.key_pressed(*key)) {
                self.last_key = Some(*key);
                println!("Key pressed: {:?}", *key);

                let cursor = std::io::Cursor::new(self.sound_bytes.clone());
                if let Ok(decoder) = rodio::Decoder::new(cursor) {
                    let _ = self.audio_sink.play_raw(decoder.decode_raw().unwrap());
                }
            }
        }
        
        // Add top tool bar
        egui::TopBottomPanel::top("top_panel").show(ctx, |ui| {
            egui::menu::bar(ui, |ui| {
                ui.menu_button("File", |ui| {

                    // Create Open button
                    if ui.button("Open").clicked() {
                        if let Some(path) = FileDialog::new().add_filter("Text", &["txt"]).pick_file() {
                            match fs::read_to_string(&path) {
                                Ok(content) => {
                                    self.text = content;
                                    self.file_path = Some(path); // if you track file state
                                }
                                Err(err) => {
                                    eprintln!("Failed to open file: {}", err);
                                }
                            }
                        }
                    }

                    // Create Save button
                    if ui.button("Save").clicked() {
                        self.save_file();
                    }
                });
            });
        });

        // Add central section with text field
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.add(                                            // Central text field
                egui::TextEdit::multiline(&mut self.text)
                    .desired_rows(20)
                    .desired_width(f32::INFINITY)
                    .lock_focus(true),
            );

            // Display the last pressed key
            if let Some(key) = self.last_key {
                ui.label(format!("Last key pressed: {:?}", key));
            }
        });
    }
}

impl Typewriter {
    fn save_file(&mut self) {
        if let Some(path) = rfd::FileDialog::new()
            .set_directory(dirs::download_dir().unwrap_or_else(|| std::path::PathBuf::from(".")))
            .save_file()
        {
            let mut path = path;
            if path.extension().is_none() {
                path.set_extension("txt");
            }
            if let Err(err) = std::fs::write(&path, &self.text) {
                eprintln!("Failed to save file: {err}");
            }
        }
    }
}